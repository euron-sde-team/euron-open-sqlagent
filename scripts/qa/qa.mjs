/**
 * Browser QA (make qa): signs in through the real form as each role, visits every page in
 * light and dark at desktop and phone width, saves screenshots, and fails on console
 * errors, failed or 4xx/5xx requests, broken images, error states, empty pages with no
 * explanation, and horizontal overflow.
 *
 *   make qa
 *   QA_BASE=http://localhost:5410 QA_OUT=./output node qa.mjs
 *   QA_PAGES=/projects QA_ROLES=admin QA_THEMES=dark QA_SIZES=desktop node qa.mjs
 *
 * Needs the seeded stack (make up && make demo). Uses Puppeteer's bundled Chromium; set
 * CHROME_PATH to use a local browser instead.
 */
import { mkdir } from "node:fs/promises";
import { existsSync } from "node:fs";
import path from "node:path";
import puppeteer from "puppeteer";

const BASE = process.env.QA_BASE ?? "http://localhost:5410";
const OUT = process.env.QA_OUT ?? path.resolve("output");
const PASSWORD = process.env.QA_PASSWORD ?? process.env.SQLAGENT_DEMO_PASSWORD ?? "";
const CHROME = process.env.CHROME_PATH && existsSync(process.env.CHROME_PATH) ? process.env.CHROME_PATH : undefined;

const ADMIN = "maya.chen@example.com";
const EDITOR = "arjun.mehta@example.com";
const VIEWER = "sofia.lopez@example.com";

// Pages per role. Placeholders are resolved from the seeded data once.
const P = "/projects/:retail";
const ROLE_PAGES = {
  anonymous: ["/login"],
  admin: [
    "/projects",
    P,
    `${P}/ask`,
    `${P}/ask?c=:followup`,
    `${P}/ask?c=:refused`,
    `${P}/ask?c=:subs`,
    `${P}/history`,
    `${P}/history?tab=queries`,
    `${P}/templates`,
    `${P}/connections`,
    `${P}/connections/:shop`,
    `${P}/connections/:sqlite`,
    `${P}/audit`,
    `${P}/settings`,
    `${P}/settings?tab=members`,
    `${P}/settings?tab=providers`,
    `${P}/settings?tab=api-keys`,
    `${P}/settings?tab=organization`,
    "/projects/:people",
    "/projects/:people/ask?c=:salaries",
    "/projects/:people/connections/:mysql",
    "/admin/users",
    "/admin/system",
    "/admin/audit",
    "/admin/settings",
  ],
  editor: [P, `${P}/ask`, `${P}/ask?c=:followup`, `${P}/connections`, "/projects/:people"],
  viewer: [P, `${P}/ask?c=:followup`, `${P}/history`, `${P}/connections/:shop`, `${P}/settings`],
};
const ONLY = process.env.QA_PAGES ? new Set(process.env.QA_PAGES.split(",")) : null;
const ROLES = (process.env.QA_ROLES ?? "anonymous,admin,editor,viewer").split(",");
const THEMES = (process.env.QA_THEMES ?? "light,dark").split(",");
const SIZES = {
  desktop: { width: 1440, height: 900 },
  phone: { width: 390, height: 844, isMobile: true, hasTouch: true, deviceScaleFactor: 2 },
};
const SIZE_KEYS = (process.env.QA_SIZES ?? "desktop,phone").split(",");
const FULL = process.env.QA_FULL !== "0";

function slug(p) {
  return p.replace(/^\//, "").replace(/[/:?=]/g, "-") || "home";
}

async function api(token, method, url, body) {
  const resp = await fetch(`${BASE}${url}`, {
    method,
    headers: { authorization: `Bearer ${token}`, "content-type": "application/json", "x-sqa-csrf": "1" },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!resp.ok) throw new Error(`${method} ${url}: ${resp.status} ${await resp.text()}`);
  return resp.status === 204 ? null : resp.json();
}

async function token(email) {
  const resp = await fetch(`${BASE}/api/v1/auth/login`, {
    method: "POST",
    headers: { "content-type": "application/json", "x-sqa-csrf": "1" },
    body: JSON.stringify({ email, password: PASSWORD }),
  });
  if (!resp.ok) throw new Error(`sign-in for ${email} failed (${resp.status}): run make demo first`);
  return (await resp.json()).session_token;
}

/** Ids of seeded records for the parameterised pages. */
async function resolveIds() {
  const t = await token(ADMIN);
  const projects = await api(t, "GET", "/api/v1/projects");
  const retail = projects.find((p) => p.slug === "retail-analytics");
  const people = projects.find((p) => p.slug === "people-team");
  if (!retail || !people) throw new Error("the demo projects are missing: run make demo");
  const conns = await api(t, "GET", `/api/v1/projects/${retail.id}/connections`);
  const hrConns = await api(t, "GET", `/api/v1/projects/${people.id}/connections`);
  const convs = (await api(t, "GET", `/api/v1/projects/${retail.id}/conversations?limit=100`)).items;
  const hr = (await api(t, "GET", `/api/v1/projects/${people.id}/conversations?limit=100`)).items;
  const conv = (title) => convs.find((c) => c.title === title)?.id ?? "missing";
  return {
    retail: retail.id,
    people: people.id,
    shop: conns.find((c) => c.kind === "postgresql")?.id ?? "missing",
    sqlite: conns.find((c) => c.kind === "sqlite")?.id ?? "missing",
    mysql: hrConns[0]?.id ?? "missing",
    followup: conv("How many orders were placed this year?"),
    refused: conv("Delete all cancelled orders"),
    subs: conv("Monthly revenue from invoices this year"),
    salaries: hr.find((c) => c.title === "Average salary by department")?.id ?? "missing",
  };
}

async function signInForm(page, email) {
  await page.goto(`${BASE}/login`, { waitUntil: "networkidle2" });
  await page.type("#email", email);
  await page.type("#password", PASSWORD);
  await Promise.all([page.waitForNavigation({ waitUntil: "networkidle2" }), page.click("button[type=submit]")]);
}

function watch(page, sink) {
  page.on("console", (m) => {
    if (m.type() === "error") sink.push(m.text());
  });
  page.on("pageerror", (e) => sink.push(`pageerror: ${e.message}`));
  page.on("requestfailed", (r) => {
    const err = r.failure()?.errorText ?? "";
    if (!err.includes("ERR_ABORTED")) sink.push(`requestfailed ${r.url()} ${err}`);
  });
  page.on("response", (r) => {
    if (r.status() >= 400) sink.push(`HTTP ${r.status()} ${r.url()}`);
  });
}

async function inspect(page) {
  return page.evaluate(() => {
    const overflow = document.documentElement.scrollWidth - window.innerWidth;
    const broken = [...document.images].filter((img) => img.complete && img.naturalWidth === 0).map((img) => img.src);
    const errorStates = [...document.querySelectorAll("[data-qa='error-state']")].map((el) => el.textContent?.slice(0, 80) ?? "");
    const main = document.querySelector("main") ?? document.body;
    const text = (main.textContent ?? "").replace(/\s+/g, " ").trim();
    return { overflow, broken, errorStates, empty: text.length < 40 };
  });
}

async function main() {
  await mkdir(OUT, { recursive: true });
  const ids = await resolveIds();
  const browser = await puppeteer.launch({ executablePath: CHROME, headless: true, args: ["--no-sandbox"] });
  const problems = [];
  let visited = 0;

  for (const role of ROLES) {
    const pages = ROLE_PAGES[role].filter((p) => !ONLY || ONLY.has(p));
    if (!pages.length) continue;
    for (const theme of THEMES) {
      for (const sizeKey of SIZE_KEYS) {
        const ctx = await browser.createBrowserContext();
        const page = await ctx.newPage();
        await page.setViewport(SIZES[sizeKey]);
        await page.evaluateOnNewDocument((t) => {
          try {
            localStorage.setItem("theme", t);
          } catch {}
        }, theme);
        const errors = [];
        watch(page, errors);
        const who = { admin: ADMIN, editor: EDITOR, viewer: VIEWER }[role];
        if (who) await signInForm(page, who);
        for (const p of pages) {
          const url = p.replace(/:(\w+)/g, (_, k) => ids[k] ?? k);
          errors.length = 0;
          await page.goto(`${BASE}${url}`, { waitUntil: "networkidle2", timeout: 60_000 });
          await new Promise((r) => setTimeout(r, 1200));
          const found = await inspect(page);
          const file = path.join(OUT, `${role}-${sizeKey}-${theme}-${slug(p)}.png`);
          await page.screenshot({ path: file, fullPage: FULL });
          const issues = [...errors];
          if (found.overflow > 1) issues.push(`horizontal overflow ${found.overflow}px`);
          for (const src of found.broken) issues.push(`broken image ${src}`);
          for (const text of found.errorStates) issues.push(`error state: ${text}`);
          if (found.empty) issues.push("page is empty with no explanation");
          if (issues.length) problems.push({ role, page: p, theme, size: sizeKey, issues });
          visited += 1;
          console.log(`${issues.length ? "WARN" : "ok  "} ${role} ${sizeKey} ${theme} ${p}${issues.length ? `: ${issues.join(" | ")}` : ""}`);
        }
        await ctx.close();
      }
    }
  }
  await browser.close();
  console.log(`\n${visited} page views, ${problems.length} with problems. Screenshots in ${OUT}`);
  if (problems.length) process.exitCode = 1;
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
