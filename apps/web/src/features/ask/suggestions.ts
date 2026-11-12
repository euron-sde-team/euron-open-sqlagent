import type { SchemaTable } from "@/lib/api/types";

/** A few questions that fit the connected database, to start from. */
export function suggestionsFor(tables: SchemaTable[], templates: string[]): string[] {
  const out = [...templates];
  const real = tables.filter((t) => t.kind === "table");
  for (const t of real) {
    if (out.length >= 4) break;
    const text = (t.columns ?? []).find((c) => c.sample_values && c.sample_values.length > 1 && !c.primary_key);
    out.push(text ? `How many ${t.name.replace(/_/g, " ")} per ${text.name.replace(/_/g, " ")}?` : `How many ${t.name.replace(/_/g, " ")} are there?`);
  }
  return Array.from(new Set(out)).slice(0, 4);
}
