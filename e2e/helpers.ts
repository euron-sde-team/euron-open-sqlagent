import { type APIRequestContext, type Browser, type BrowserContext, expect, type Page, request } from "@playwright/test";

const BASE = process.env.WEB_URL || "http://localhost:5410";
export const MAILPIT = process.env.MAILPIT_URL || "http://localhost:5425";
export const PASSWORD = process.env.E2E_PASSWORD || process.env.SQLAGENT_DEMO_PASSWORD || "";
/** The demo databases' read-only login, as the API container reaches them inside Compose. */
export const READER_PASSWORD = process.env.E2E_READER_PASSWORD || "";
export const SHOP_HOST = process.env.E2E_SHOP_HOST || "source-postgres";
export const ADMIN = { email: process.env.E2E_EMAIL || "maya.chen@example.com", password: PASSWORD };
export const EDITOR = "arjun.mehta@example.com";
export const VIEWER = "sofia.lopez@example.com";

/** Mutations through the API carry the CSRF header the web app sends. */
export const CSRF = { "x-sqa-csrf": "1" };

/** A per-run suffix so suites can run repeatedly against the same demo database. */
export const RUN = process.env.E2E_RUN || Date.now().toString(36).slice(-5);

/** Fail the test on any console error or CSP violation the page reports. */
export function watchConsole(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (m) => {
    if (m.type() === "error") errors.push(m.text());
  });
  page.on("pageerror", (e) => errors.push(e.message));
  return errors;
}

async function retrying(fn: () => Promise<import("@playwright/test").APIResponse>) {
  for (let i = 0; i < 10; i++) {
    const resp = await fn();
    if (resp.status() !== 429) return resp;
    await new Promise((r) => setTimeout(r, Number(resp.headers()["retry-after"] ?? "5") * 1000));
  }
  return fn();
}

/** An API client signed in as someone (waits out the sign-in limit if needed). */
export async function apiAs(email: string, password = PASSWORD): Promise<APIRequestContext> {
  const ctx = await request.newContext({ baseURL: BASE, extraHTTPHeaders: CSRF });
  const resp = await retrying(() => ctx.post("/api/v1/auth/login", { data: { email, password } }));
  expect(resp.status(), await resp.text()).toBe(200);
  return ctx;
}

/** JSON from the API, asserting success. */
export async function call<T = unknown>(ctx: APIRequestContext, method: string, path: string, data?: unknown): Promise<T> {
  const resp = await retrying(() => ctx.fetch(path, { method, data }));
  expect(resp.status(), `${method} ${path}: ${await resp.text()}`).toBeLessThan(300);
  return (resp.status() === 204 ? null : await resp.json()) as T;
}

/** A browser context carrying the session of an existing account. */
export async function signedInContext(browser: Browser, email: string): Promise<{ context: BrowserContext; page: Page }> {
  const api = await apiAs(email);
  const state = await api.storageState();
  await api.dispose();
  const context = await browser.newContext({ storageState: state });
  return { context, page: await context.newPage() };
}

export interface Project {
  id: string;
  org_id: string;
  name: string;
  slug: string;
}

/** The seeded demo project by slug. */
export async function demoProject(api: APIRequestContext, slug = "retail-analytics"): Promise<Project> {
  const projects = await call<Project[]>(api, "GET", "/api/v1/projects");
  const found = projects.find((p) => p.slug === slug);
  expect(found, "run make demo first").toBeTruthy();
  return found as Project;
}

/** A fresh project for a suite, in the demo organization, with the built-in mock provider. */
export async function newProject(api: APIRequestContext, name: string): Promise<Project> {
  const demo = await demoProject(api);
  const p = await call<Project>(api, "POST", "/api/v1/projects", { org_id: demo.org_id, name: `${name} ${RUN}` });
  await call(api, "POST", `/api/v1/projects/${p.id}/providers`, { name: "mock", kind: "mock" });
  return p;
}

/** Pick an option in one of the web app's custom selects. */
export async function choose(page: Page, trigger: string, option: string | RegExp): Promise<void> {
  await page.getByRole("combobox", { name: trigger }).click();
  await page.getByRole("option", { name: option }).first().click();
}
