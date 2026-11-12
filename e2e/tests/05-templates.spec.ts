import { expect, test } from "@playwright/test";

import { ADMIN, apiAs, demoProject, RUN, watchConsole } from "../helpers";

test("save an answer as a template and run it again", async ({ page }) => {
  const api = await apiAs(ADMIN.email);
  const project = await demoProject(api, "people-team");
  const errors = watchConsole(page);
  await page.goto(`/projects/${project.id}/ask`);
  await page.getByRole("textbox", { name: "Ask a question" }).fill("Which department has the most employees?");
  await page.getByRole("button", { name: "Ask", exact: true }).click();
  const answer = page.locator("[data-qa=answer]").first();
  await expect(answer.getByText("Answered")).toBeVisible({ timeout: 60_000 });
  await answer.getByRole("button", { name: "Save as template" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Name").fill(`Biggest department ${RUN}`);
  await dialog.getByRole("button", { name: "Save template" }).click();
  await page.goto(`/projects/${project.id}/templates`);
  const card = page.locator("[data-qa=template]", { hasText: `Biggest department ${RUN}` });
  await expect(card.getByText("Saved SQL")).toBeVisible();
  await card.getByRole("button", { name: "Run" }).click();
  await expect(page).toHaveURL(/\/ask\?c=/);
  await expect(page.locator("[data-qa=answer]").first().getByText("Answered")).toBeVisible({ timeout: 60_000 });
  await expect(page.locator("[data-qa=answer]").first().getByRole("cell", { name: "Engineering" })).toBeVisible();
  // Clean up so reruns start the same.
  const list = (await (await api.get(`/api/v1/projects/${project.id}/templates`)).json()) as { id: string; name: string }[];
  for (const t of list.filter((x) => x.name.endsWith(RUN))) await api.delete(`/api/v1/projects/${project.id}/templates/${t.id}`);
  expect(errors).toEqual([]);
  await api.dispose();
});
