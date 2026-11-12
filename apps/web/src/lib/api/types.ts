/**
 * Named aliases over the generated OpenAPI types (`pnpm gen:api`). Nothing here is
 * hand-written: every shape comes from `schema.d.ts`, which is generated from
 * docs/api/openapi.yaml.
 */
import type { components } from "./schema";

type S = components["schemas"];

export type User = S["UserOut"];
export type UserCreate = S["UserCreate"];
export type UserUpdate = S["UserUpdate"];
export type SignIn = S["SignInOut"];
export type AuditEntry = S["AuditOut"];
export type AuditPage = S["Page_AuditOut_"];
export type SystemInfo = S["SystemInfo"];
export type QueueInfo = S["QueueInfo"];
export type Role = NonNullable<UserCreate["role"]>;
export type PublicSettings = S["PublicSettings"];
export type AdminSettings = S["AdminSettings"];
export type SettingsUpdate = S["SettingsUpdate"];

export type Org = S["OrgOut"];
export type OrgRole = NonNullable<Org["role"]>;
export type OrgMember = S["OrgMemberOut"];
export type OrgMemberAdd = S["OrgMemberAdd"];

export type Project = S["ProjectOut"];
export type ProjectCreate = S["ProjectCreate"];
export type ProjectUpdate = S["ProjectUpdate"];
export type ProjectRole = NonNullable<Project["role"]>;
export type Member = S["MemberOut"];
export type ApiKey = S["ApiKeyOut"];
export type ApiKeyCreated = S["ApiKeyCreated"];
export type Scope = NonNullable<S["ApiKeyCreate"]["scopes"]>[number];

export type Provider = S["ProviderOut"];
export type ProviderCreate = S["ProviderCreate"];
export type ProviderUpdate = S["ProviderUpdate"];
export type ProviderKind = Provider["kind"];
export type ProviderTest = S["ProviderTest"];

export type Connection = S["ConnectionOut"];
export type ConnectionKind = Connection["kind"];
export type ServerConnection = S["ServerConnection"];
export type ConnectionUpdate = S["ConnectionUpdate"];
export type ConnectionTest = S["TestResult"];
export type DatabaseSchema = S["SchemaOut"];
export type SchemaTable = S["SchemaTable"];
export type SchemaColumn = S["SchemaColumn"];

export type AskRequest = S["AskRequest"];
export type Answer = S["MessageOut"];
export type AnswerStatus = Answer["status"];
export type Conversation = S["ConversationOut"];
export type ConversationDetail = S["ConversationDetail"];
export type ConversationPage = S["ConversationPage"];

export type Execution = S["ExecutionOut"];
export type ExecutionWithRows = S["ExecutionWithRows"];
export type ExecutionPage = S["Page_ExecutionOut_"];
export type RowsPage = S["RowsPage"];
export type ResultColumn = S["ColumnIn"];
export type ChartSuggestion = S["ChartSuggestion"];
export type ChartType = ChartSuggestion["type"];

export type Explanation = S["ExplainOut"];
export type ExplainRequestBody = S["ExplainRequest"];
export type Validation = S["Validation"];
export type Dialect = NonNullable<S["SqlInput"]["dialect"]>;

export type Template = S["TemplateOut"];
export type TemplateCreate = S["TemplateCreate"];

export type Overview = S["Overview"];
export type UsageReport = S["UsageReport"];
export type UsageDay = S["UsageByDay"];
