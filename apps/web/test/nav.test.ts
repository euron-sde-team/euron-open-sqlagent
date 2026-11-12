import { describe, expect, it } from "vitest";

import { activeHref, hrefOf, NAV, projectIdFrom, visibleTo, type NavItem } from "@/lib/nav";

const PID = "5bff5132-b0f6-4c20-93cb-7dce7f4e9629";
const items = NAV.flatMap((g) => g.items);
const item = (label: string) => items.find((i) => i.label === label) as NavItem;

describe("projectIdFrom", () => {
  it("reads the project id from project paths", () => {
    expect(projectIdFrom(`/projects/${PID}`)).toBe(PID);
    expect(projectIdFrom(`/projects/${PID}/connections/abc`)).toBe(PID);
  });
  it("returns null outside a project or for a malformed id", () => {
    expect(projectIdFrom("/projects")).toBeNull();
    expect(projectIdFrom("/admin/users")).toBeNull();
    expect(projectIdFrom("/projects/not-a-uuid/ask")).toBeNull();
    expect(projectIdFrom(`/projects/${PID}extra`)).toBeNull();
  });
});

describe("hrefOf", () => {
  it("prefixes project items with the current project", () => {
    expect(hrefOf(item("Overview"), PID)).toBe(`/projects/${PID}`);
    expect(hrefOf(item("Ask"), PID)).toBe(`/projects/${PID}/ask`);
  });
  it("has no href for a project item outside a project", () => {
    expect(hrefOf(item("Ask"), null)).toBeNull();
  });
  it("keeps admin items absolute", () => {
    expect(hrefOf(item("Users"), null)).toBe("/admin/users");
    expect(hrefOf(item("Users"), PID)).toBe("/admin/users");
  });
});

describe("visibleTo", () => {
  it("shows admin items to admins only", () => {
    expect(visibleTo(item("System"), "admin", null)).toBe(true);
    expect(visibleTo(item("System"), "user", PID)).toBe(false);
    expect(visibleTo(item("System"), undefined, PID)).toBe(false);
  });
  it("shows project items to anyone signed in, inside a project", () => {
    expect(visibleTo(item("Ask"), "user", PID)).toBe(true);
    expect(visibleTo(item("Ask"), "admin", PID)).toBe(true);
    expect(visibleTo(item("Ask"), "user", null)).toBe(false);
    expect(visibleTo(item("Ask"), null, PID)).toBe(false);
  });
  it("shows the project audit log to project admins and instance admins only", () => {
    expect(visibleTo(item("Audit log"), "user", PID, "admin")).toBe(true);
    expect(visibleTo(item("Audit log"), "user", PID, "editor")).toBe(false);
    expect(visibleTo(item("Audit log"), "user", PID, "viewer")).toBe(false);
    expect(visibleTo(item("Audit log"), "admin", PID, null)).toBe(true);
    expect(visibleTo(item("Audit log"), "user", null, "admin")).toBe(false);
  });
});

describe("activeHref", () => {
  it("picks the longest matching prefix", () => {
    expect(activeHref(`/projects/${PID}/connections/x`, PID)).toBe(`/projects/${PID}/connections`);
    expect(activeHref(`/projects/${PID}/ask`, PID)).toBe(`/projects/${PID}/ask`);
    expect(activeHref(`/projects/${PID}`, PID)).toBe(`/projects/${PID}`);
  });
  it("ignores a trailing slash", () => {
    expect(activeHref(`/projects/${PID}/history/`, PID)).toBe(`/projects/${PID}/history`);
  });
  it("matches admin pages and nothing for unknown pages", () => {
    expect(activeHref("/admin/audit", null)).toBe("/admin/audit");
    expect(activeHref("/projects", null)).toBeNull();
  });
});
