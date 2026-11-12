import {
  ActivityIcon,
  BookmarkIcon,
  DatabaseIcon,
  GaugeIcon,
  HistoryIcon,
  MessageSquareTextIcon,
  ScrollTextIcon,
  SettingsIcon,
  SlidersHorizontalIcon,
  UsersIcon,
  type LucideIcon,
} from "lucide-react";

export type Audience = "project" | "project-admin" | "admin";

export interface NavItem {
  /** A path; inside a project, relative to /projects/<id>. */
  href: string;
  label: string;
  icon: LucideIcon;
  audience: Audience;
}

export interface NavGroup {
  label: string;
  items: NavItem[];
}

export const NAV: NavGroup[] = [
  {
    label: "Ask",
    items: [
      { href: "", label: "Overview", icon: GaugeIcon, audience: "project" },
      { href: "/ask", label: "Ask", icon: MessageSquareTextIcon, audience: "project" },
      { href: "/history", label: "History", icon: HistoryIcon, audience: "project" },
      { href: "/templates", label: "Templates", icon: BookmarkIcon, audience: "project" },
    ],
  },
  {
    label: "Data",
    items: [{ href: "/connections", label: "Connections", icon: DatabaseIcon, audience: "project" }],
  },
  {
    label: "Govern",
    items: [
      { href: "/audit", label: "Audit log", icon: ScrollTextIcon, audience: "project-admin" },
      { href: "/settings", label: "Settings", icon: SlidersHorizontalIcon, audience: "project" },
    ],
  },
  {
    label: "Instance",
    items: [
      { href: "/admin/users", label: "Users", icon: UsersIcon, audience: "admin" },
      { href: "/admin/system", label: "System", icon: ActivityIcon, audience: "admin" },
      { href: "/admin/audit", label: "Instance audit", icon: ScrollTextIcon, audience: "admin" },
      { href: "/admin/settings", label: "Instance settings", icon: SettingsIcon, audience: "admin" },
    ],
  },
];

/** The project id in a path like /projects/<id>/ask, or null. */
export function projectIdFrom(pathname: string): string | null {
  const m = /^\/projects\/([0-9a-f-]{36})(?:\/|$)/.exec(pathname);
  return m?.[1] ?? null;
}

/** The real href of an item: project items are prefixed with the current project. */
export function hrefOf(item: NavItem, projectId: string | null): string | null {
  if (item.audience === "admin") return item.href;
  return projectId ? `/projects/${projectId}${item.href}` : null;
}

/**
 * Whether someone sees an item: instance items need an instance admin, project items a
 * project, and the project audit log the project admin role.
 */
export function visibleTo(
  item: NavItem,
  role: string | null | undefined,
  projectId: string | null,
  projectRole?: string | null,
): boolean {
  if (item.audience === "admin") return role === "admin";
  if (item.audience === "project-admin") return !!projectId && (projectRole === "admin" || role === "admin");
  return !!role && !!projectId;
}

/** The nav item a path belongs to: the longest matching prefix. */
export function activeHref(pathname: string, projectId: string | null): string | null {
  const path = pathname.replace(/\/+$/, "") || "/";
  const hrefs = NAV.flatMap((g) => g.items)
    .map((i) => hrefOf(i, projectId))
    .filter((h): h is string => !!h);
  return hrefs.filter((h) => path === h || path.startsWith(`${h}/`)).sort((a, b) => b.length - a.length)[0] ?? null;
}
