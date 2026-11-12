import { expect, test } from "@playwright/test";

import { ADMIN, apiAs, demoProject, watchConsole } from "../helpers";

/** A3 and A10 in the browser: a write is refused and never runs; a pasted query is explained, not run. */
test("a destructive question is refused, and a pasted query is explained without running", async ({ page }) => {
  const api = await apiAs(ADMIN.email);
  const project = await demoProject(api);
  const errors = watchConsole(page);
  await page.goto(`/projects/${project.id}/ask`);
  await page.getByRole("combobox", { name: "Database to ask about" }).click();
  await page.getByRole("option", { name: "Shop (PostgreSQL)" }).click();
  await page.getByRole("textbox", { name: "Ask a question" }).fill("Delete all cancelled orders");
  await page.getByRole("button", { name: "Ask", exact: true }).click();
  const answer = page.locator("[data-qa=answer]").first();
  await expect(answer.getByText("Refused", { exact: true })).toBeVisible({ timeout: 60_000 });
  await expect(answer.locator("[data-qa=guard-refused]")).toBeVisible();
  await expect(answer.getByRole("alert")).toContainText("This query was not run");
  await expect(answer.locator("[data-qa=result]")).toHaveCount(0);

  await page.getByRole("button", { name: "Explain SQL" }).click();
  const dialog = page.getByRole("dialog");
  await dialog
    .getByLabel("SQL")
    .fill("SELECT c.country, sum(o.total_amount) AS revenue FROM orders o JOIN customers c ON c.id = o.customer_id GROUP BY c.country ORDER BY revenue DESC LIMIT 5");
  await dialog.getByRole("button", { name: "Explain" }).click();
  const out = dialog.locator("[data-qa=explanation]");
  await expect(out).toContainText("One read-only query");
  await expect(out).toContainText("Not executed");
  await expect(out).toContainText("customers");
  await dialog.getByLabel("SQL").fill("DROP TABLE orders");
  await dialog.getByRole("button", { name: "Explain" }).click();
  await expect(out).toContainText("SQLAgent would not run this");
  expect(errors).toEqual([]);
  await api.dispose();
});
