/**
 * Curated README screenshots and tour frames from the seeded stack (real data only).
 *
 *   make up && make demo
 *   make screenshots     (this script, then make-tour.sh stitches docs/assets/tour.gif)
 *
 * The tour asks a real question: the editor types it on the Ask page, the worker answers
 * it with the mock provider against the demo shop database, and the page shows the result.
 *
 * Writes docs/assets/screenshots/NN-name.png and scripts/qa/output/tour/NN.png.
 */
import { mkdir, rm } from "node:fs/promises";
import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import puppeteer from "puppeteer";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const BASE = process.env.QA_BASE ?? "http://localhost:5410";
const PASSWORD = process.env.QA_PASSWORD ?? process.env.SQLAGENT_DEMO_PASSWORD ?? "";
const SHOTS = path.resolve(HERE, "../../docs/assets/screenshots");
const TOUR = path.resolve(HERE, "output/tour");
const CHROME = process.env.CHROME_PATH && existsSync(process.env.CHROME_PATH) ? process.env.CHROME_PATH : undefined;
const DESKTOP = { width: 1440, height: 900, deviceScaleFactor: 1 };
const PHONE = { width: 390, height: 844, isMobile: true, hasTouch: true, deviceScaleFactor: 2 };

const ADMIN = "maya.chen@example.com";
const EDITOR = "arjun.mehta@example.com";

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let tourIndex = 0;

async function api(token, method, url) {
  const resp = await fetch(`${BASE}${url}`, { method, headers: { authorization: `Bearer ${token}`, "x-sqa-csrf": "1" } });
  if (!resp.ok) throw new Error(`${method} ${url}: ${resp.status} ${await resp.text()}`);
  return resp.json();
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

async function settle(page, ms = 1200) {
  await page.waitForNetworkIdle({ idleTime: 400, timeout: 4_000 }).catch(() => {});
  await sleep(ms);
}

async function shot(page, name, { tour = true, curated = true } = {}) {
  await page.mouse.move(1, 1);
  await sleep(250);
  if (curated) await page.screenshot({ path: path.join(SHOTS, `${name}.png`) });
  if (tour) {
    await page.screenshot({
      path: path.join(TOUR, `${String(++tourIndex).padStart(2, "0")}.png`),
      clip: { x: 0, y: 0, width: DESKTOP.width, height: DESKTOP.height },
    });
  }
  console.log(`saved ${name}`);
}

async function open(page, url, ms = 1500) {
  await page.goto(`${BASE}${url}`, { waitUntil: "networkidle2", timeout: 60_000 });
  await settle(page, ms);
}

async function session(browser, email, { theme = "light", viewport = DESKTOP } = {}) {
  const ctx = await browser.createBrowserContext();
  const page = await ctx.newPage();
  await page.setViewport(viewport);
  await page.evaluateOnNewDocument((t) => {
    try {
      localStorage.setItem("theme", t);
    } catch {}
  }, theme);
  if (email) {
    await page.goto(`${BASE}/login`, { waitUntil: "networkidle2" });
    await page.type("#email", email);
    await page.type("#password", PASSWORD);
    await Promise.all([page.waitForNavigation({ waitUntil: "networkidle2" }), page.click("button[type=submit]")]);
  }
  return { ctx, page };
}

async function scrollTo(page, selector, index = 0) {
  await page.evaluate(
    (s, i) => {
      const el = document.querySelectorAll(s)[i];
      if (el) window.scrollTo({ top: el.getBoundingClientRect().top + window.scrollY - 90 });
    },
    selector,
    index,
  );
  await sleep(500);
}

async function main() {
  await rm(TOUR, { recursive: true, force: true });
  await mkdir(SHOTS, { recursive: true });
  await mkdir(TOUR, { recursive: true });
  const t = await token(ADMIN);
  const projects = await api(t, "GET", "/api/v1/projects");
  const retail = projects.find((p) => p.slug === "retail-analytics");
  const conns = await api(t, "GET", `/api/v1/projects/${retail.id}/connections`);
  const shop = conns.find((c) => c.kind === "postgresql");
  const convs = (await api(t, "GET", `/api/v1/projects/${retail.id}/conversations?limit=100`)).items;
  const conv = (title) => convs.find((c) => c.title === title).id;
  const P = `/projects/${retail.id}`;
  const browser = await puppeteer.launch({ executablePath: CHROME, headless: true, args: ["--no-sandbox"] });
  try {
    {
      const { ctx, page } = await session(browser, null);
      await open(page, "/login");
      await shot(page, "01-sign-in");
      await ctx.close();
    }
    {
      const { ctx, page } = await session(browser, ADMIN);
      await open(page, P, 2000);
      await shot(page, "02-overview");
      // A live question, asked in the browser.
      await open(page, `${P}/ask?connection=${shop.id}`);
      await shot(page, "03-ask", { curated: false });
      await page.type("textarea", "Revenue by country this year", { delay: 25 });
      await shot(page, "03-ask-typing", { curated: false });
      await page.keyboard.press("Enter");
      await page.waitForSelector("[data-qa=result]", { timeout: 60_000 });
      await settle(page, 1500);
      await scrollTo(page, "[data-qa=answer]");
      await shot(page, "03-ask-answer");
      await open(page, `${P}/ask?c=${conv("How many orders were placed this year?")}`);
      await scrollTo(page, "[data-qa=answer]", 1);
      await shot(page, "04-follow-up");
      await scrollTo(page, "[data-qa=answer]", 2);
      await shot(page, "05-chart");
      await open(page, `${P}/ask?c=${conv("Delete all cancelled orders")}`);
      await shot(page, "06-refused");
      await open(page, `${P}/ask?c=${conv("Monthly revenue this year")}`);
      await shot(page, "07-line-chart");
      await open(page, `${P}/ask`);
      for (const b of await page.$$("button")) {
        if (((await b.evaluate((e) => e.textContent)) ?? "").trim() === "Explain SQL") {
          await b.click();
          break;
        }
      }
      await sleep(500);
      await page.type(
        "#explain-sql",
        "SELECT c.segment, avg(o.total_amount) AS avg_order\nFROM orders o JOIN customers c ON c.id = o.customer_id\nWHERE o.status = 'delivered'\nGROUP BY c.segment\nORDER BY avg_order DESC",
      );
      for (const b of await page.$$("[role=dialog] button[type=submit]")) await b.click();
      await page.waitForSelector("[data-qa=explanation]", { timeout: 30_000 });
      await settle(page, 800);
      await shot(page, "08-explain");
      await open(page, `${P}/connections`);
      await shot(page, "09-connections");
      await open(page, `${P}/connections/${shop.id}`);
      for (const b of await page.$$("ul[aria-label=Tables] button")) {
        if (((await b.evaluate((e) => e.textContent)) ?? "").includes("public.orders")) {
          await b.click();
          break;
        }
      }
      await settle(page, 600);
      await shot(page, "10-schema");
      await open(page, `${P}/history`);
      await shot(page, "11-history");
      await open(page, `${P}/history?tab=queries`);
      await shot(page, "12-queries", { tour: false });
      await open(page, `${P}/templates`);
      await shot(page, "13-templates");
      await open(page, `${P}/audit`);
      await shot(page, "14-audit");
      await open(page, `${P}/settings?tab=providers`);
      await shot(page, "15-providers");
      await ctx.close();
    }
    {
      const { ctx, page } = await session(browser, EDITOR, { theme: "dark" });
      await open(page, `${P}/ask?c=${conv("Revenue by product category")}`);
      await scrollTo(page, "[data-qa=answer]");
      await shot(page, "16-dark-ask");
      await open(page, P, 2000);
      await shot(page, "17-dark-overview");
      await ctx.close();
    }
    {
      const { ctx, page } = await session(browser, EDITOR, { viewport: PHONE });
      await open(page, `${P}/ask?c=${conv("How many orders per status?")}`);
      await scrollTo(page, "[data-qa=answer]");
      await shot(page, "18-phone-ask", { tour: false });
      await ctx.close();
    }
  } finally {
    await browser.close();
  }
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
