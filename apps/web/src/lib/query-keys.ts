/**
 * Query keys in one place, so invalidation after a mutation names exactly what it
 * touched. Everything inside a project starts with ["p", projectId], so leaving or
 * deleting a project drops all of it at once.
 */
export const qk = {
  me: ["auth", "me"] as const,
  publicSettings: ["settings", "public"] as const,
  adminSettings: ["settings", "admin"] as const,
  system: ["system"] as const,
  users: ["users"] as const,
  audit: (action?: string) => ["audit", { action }] as const,

  orgs: ["orgs"] as const,
  org: (oid: string) => ["org", oid] as const,
  orgMembers: (oid: string) => ["org", oid, "members"] as const,
  orgAudit: (oid: string, action?: string) => ["org", oid, "audit", { action }] as const,

  projects: ["projects"] as const,
  project: (pid: string) => ["p", pid] as const,
  members: (pid: string) => ["p", pid, "members"] as const,
  apiKeys: (pid: string) => ["p", pid, "api-keys"] as const,
  providers: (pid: string) => ["p", pid, "providers"] as const,

  overview: (pid: string) => ["p", pid, "overview"] as const,
  usage: (pid: string, days: number) => ["p", pid, "usage", days] as const,

  connections: (pid: string) => ["p", pid, "connections"] as const,
  connection: (pid: string, cid: string) => ["p", pid, "connection", cid] as const,
  schema: (pid: string, cid: string) => ["p", pid, "schema", cid] as const,

  conversations: (pid: string, filters: object = {}) => ["p", pid, "conversations", filters] as const,
  conversationsAll: (pid: string) => ["p", pid, "conversations"] as const,
  conversation: (pid: string, cid: string) => ["p", pid, "conversation", cid] as const,
  message: (pid: string, mid: string) => ["p", pid, "message", mid] as const,
  executions: (pid: string, filters: object = {}) => ["p", pid, "executions", filters] as const,
  executionsAll: (pid: string) => ["p", pid, "executions"] as const,
  rows: (pid: string, eid: string, offset: number, limit: number) => ["p", pid, "rows", eid, offset, limit] as const,
  templates: (pid: string) => ["p", pid, "templates"] as const,
  projectAudit: (pid: string, filters: object = {}) => ["p", pid, "audit", filters] as const,
};

/** How long data stays fresh before a background refetch, by kind. */
export const STALE = {
  /** Something in motion (a question being answered). */
  live: 2_000,
  /** Lists that change when someone acts: refetched on focus and after mutations. */
  list: 15_000,
  /** One record being looked at. */
  detail: 10_000,
  /** Settings and catalogs that rarely change. */
  config: 60_000,
  /** A schema changes only on refresh; results never change. */
  static: 300_000,
} as const;
