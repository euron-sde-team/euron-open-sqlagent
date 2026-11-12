import { expect, test } from "@playwright/test";

import { ADMIN, apiAs, call, demoProject, signedInContext, VIEWER, watchConsole } from "../helpers";

/** A viewer reads conversations and results, and sees no control that asks, runs or changes anything. */
test("a viewer has no write-adjacent controls", async ({ browser }) => {
  const admin = await apiAs(ADMIN.email);
  const project = await demoProject(admin);
  const convs = await call<{ items: { id: string; title: string }[] }>(admin, "GET", `/api/v1/projects/${project.id}/conversations?limit=100`);
  const conv = convs.items.find((c) => c.title === "How many orders were placed this year?");
  const { context, page } = await signedInContext(browser, VIEWER);
  const errors = watchConsole(page);

  await page.goto(`/projects/${project.id}/ask?c=${conv?.id}`);
  await expect(page.locator("[data-qa=answer]").first().getByText("Answered")).toBeVisible();
  await expect(page.getByRole("textbox", { name: /Ask a/ })).toHaveCount(0);
  await expect(page.getByRole("note")).toContainText("Viewers read conversations");
  await expect(page.getByRole("button", { name: "Save as template" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Explain SQL" })).toBeDisabled();

  await page.goto(`/projects/${project.id}/connections`);
  await expect(page.locator("[data-qa=connection]").first()).toBeVisible();
  await expect(page.getByRole("button", { name: "Add a database" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Test" })).toHaveCount(0);

  await page.goto(`/projects/${project.id}/templates`);
  await expect(page.getByRole("button", { name: "Run" })).toHaveCount(0);

  await expect(page.getByRole("link", { name: "Audit log" })).toHaveCount(0);
  await page.goto(`/projects/${project.id}/settings`);
  await expect(page.getByRole("tab", { name: /API keys/ })).toHaveCount(0);
  await page.getByRole("tab", { name: /Model providers/ }).click();
  await expect(page.getByRole("button", { name: "Add provider" })).toHaveCount(0);

  // The API agrees: asking is refused for a viewer.
  const viewerApi = await apiAs(VIEWER);
  const resp = await viewerApi.post(`/api/v1/projects/${project.id}/chat`, { data: { question: "x", connection_id: conv?.id } });
  expect(resp.status()).toBe(403);
  await viewerApi.dispose();
  expect(errors).toEqual([]);
  await context.close();
  await admin.dispose();
});
