import { expect, test } from "@playwright/test";

import { apiAs, ADMIN, call, newProject, READER_PASSWORD, SHOP_HOST, watchConsole } from "../helpers";

/**
 * A1, A9, A6 in the browser: connect a database through the web app, ask a question, see
 * the validated SQL, the result as a table and a chart, then follow up.
 */
test("connect a database, ask, see the SQL, the table and a chart, then follow up", async ({ page }) => {
  const api = await apiAs(ADMIN.email);
  const project = await newProject(api, "E2E ask");
  const errors = watchConsole(page);

  await page.goto(`/projects/${project.id}/connections`);
  await expect(page.getByText("No databases yet")).toBeVisible();
  await page.getByRole("button", { name: "Add a database" }).first().click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Name", { exact: true }).fill("Shop");
  await dialog.getByLabel("Host").fill(SHOP_HOST);
  await dialog.getByLabel("Port").fill("5432");
  await dialog.getByLabel("Database", { exact: true }).fill("shop");
  await dialog.getByLabel("Username").fill("sqlagent_reader");
  await dialog.getByLabel("Password").fill(READER_PASSWORD);
  // Example values let 'only cancelled ones' match the real spelling.
  await dialog.getByRole("switch", { name: "Include example values in prompts" }).click();
  await dialog.getByRole("button", { name: "Test connection" }).click();
  await expect(dialog.getByRole("status")).toContainText("Connected read-only");
  await expect(dialog.getByRole("status")).toContainText("session confirmed read-only");
  await dialog.getByRole("button", { name: "Save connection" }).click();
  await expect(page.getByRole("heading", { name: "Shop" })).toBeVisible();

  // The password is never shown again: not in the page, not in the API.
  const conns = await call<{ id: string; has_password: boolean }[]>(api, "GET", `/api/v1/projects/${project.id}/connections`);
  expect(conns[0]?.has_password).toBe(true);
  expect(JSON.stringify(conns)).not.toContain(READER_PASSWORD);

  await page.getByRole("link", { name: "Ask" }).first().click();
  await page.getByRole("textbox", { name: "Ask a question" }).fill("How many orders per status?");
  await page.getByRole("button", { name: "Ask", exact: true }).click();
  const first = page.locator("[data-qa=answer]").first();
  await expect(first.getByText("Answered")).toBeVisible({ timeout: 60_000 });
  await expect(first.locator("[data-qa=guard-validated]")).toBeVisible();
  await expect(first.locator("pre")).toContainText("GROUP BY t0.status");
  // A9: the shape fits a chart, so one is offered (and shown) without asking.
  await expect(first.getByRole("tab", { name: "Pie" })).toHaveAttribute("aria-selected", "true");
  await expect(first.getByRole("img", { name: /pie chart of order_count by status/ })).toBeVisible();
  await first.getByRole("tab", { name: "Bar" }).click();
  await expect(first.getByRole("img", { name: /bar chart/ })).toBeVisible();
  await first.getByRole("tab", { name: "Table" }).click();
  await expect(first.getByRole("cell", { name: "delivered" })).toBeVisible();

  // A6: a follow-up keeps the question and changes only what it names.
  await expect(page).toHaveURL(/\?c=/);
  await page.getByRole("textbox", { name: "Ask a follow-up question" }).fill("only cancelled ones");
  await page.keyboard.press("Enter");
  const second = page.locator("[data-qa=answer]").nth(1);
  await expect(second.getByText("Answered")).toBeVisible({ timeout: 60_000 });
  await expect(second.locator("pre")).toContainText("t0.status = 'cancelled'");
  await expect(second.locator("pre")).toContainText("COUNT(*)");

  // CSV export of the stored result.
  const download = page.waitForEvent("download");
  await first.getByRole("button", { name: "CSV" }).click();
  expect((await download).suggestedFilename()).toMatch(/^sqlagent-.*\.csv$/);

  expect(errors).toEqual([]);
  await api.dispose();
});
