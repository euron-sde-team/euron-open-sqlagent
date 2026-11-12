import { expect, test } from "@playwright/test";

import { ADMIN, apiAs, call, demoProject, watchConsole } from "../helpers";

/** A5 and A7 in the browser: the real schema, the history, and the audit log of every query. */
test("the schema explorer, the history and the audit log", async ({ page }) => {
  const api = await apiAs(ADMIN.email);
  const project = await demoProject(api);
  const conns = await call<{ id: string; name: string }[]>(api, "GET", `/api/v1/projects/${project.id}/connections`);
  const shop = conns.find((c) => c.name === "Shop (PostgreSQL)");
  const errors = watchConsole(page);

  await page.goto(`/projects/${project.id}/connections/${shop?.id}`);
  await expect(page.getByRole("button", { name: /public\.orders/ })).toBeVisible();
  await page.getByRole("button", { name: /public\.orders/ }).click();
  const table = page.locator("[data-qa=schema-table]");
  await expect(table.getByRole("cell", { name: "total_amount" })).toBeVisible();
  await expect(table.getByText("public.customers.id")).toBeVisible();
  await expect(table.getByText("delivered", { exact: false })).toBeVisible();
  await page.getByRole("textbox", { name: "Find a table or column" }).fill("line_total");
  await expect(page.getByRole("button", { name: /public\.order_items/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /public\.customers/ })).toHaveCount(0);

  await page.goto(`/projects/${project.id}/history`);
  await expect(page.getByRole("link", { name: "How many orders were placed this year?" })).toBeVisible();
  await page.getByRole("tab", { name: "Queries" }).click();
  await expect(page.getByText("Refused by the guard").first()).toBeVisible();

  await page.goto(`/projects/${project.id}/audit`);
  await expect(page.getByText("query.executed").first()).toBeVisible();
  await page.getByRole("combobox", { name: "Database" }).click();
  await page.getByRole("option", { name: "Shop (PostgreSQL)" }).click();
  await page.getByRole("textbox", { name: "Filter by action" }).fill("query.refused");
  await expect(page.getByText("query.refused").first()).toBeVisible();
  await expect(page.getByText("query.executed")).toHaveCount(0);
  expect(errors).toEqual([]);
  await api.dispose();
});
