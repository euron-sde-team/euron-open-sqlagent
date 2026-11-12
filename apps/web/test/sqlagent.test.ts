import { describe, expect, it } from "vitest";

import { dayRows } from "@/components/charts/day-charts";
import { chartData } from "@/components/charts/result-chart";
import { suggestionsFor } from "@/features/ask/suggestions";
import type { SchemaTable } from "@/lib/api/types";
import { answerLabel, answerTone, executionLabel, executionTone, inFlight, kindLabel } from "@/lib/status";

describe("question and query states", () => {
  it("labels and tones every question state", () => {
    expect(answerLabel("answered")).toBe("Answered");
    expect(answerTone("answered")).toBe("success");
    expect(answerLabel("refused")).toBe("Refused");
    expect(answerTone("refused")).toBe("danger");
    expect(answerTone("no_answer")).toBe("warning");
    expect(answerLabel("whatever")).toBe("Unknown");
    expect(answerTone(null)).toBe("neutral");
  });
  it("knows which questions are still being answered", () => {
    expect(inFlight("queued")).toBe(true);
    expect(inFlight("running")).toBe(true);
    expect(inFlight("answered")).toBe(false);
    expect(inFlight(undefined)).toBe(false);
  });
  it("labels query outcomes and database kinds", () => {
    expect(executionLabel("refused")).toBe("Refused by the guard");
    expect(executionTone("scan_limit")).toBe("warning");
    expect(executionLabel("mystery")).toBe("mystery");
    expect(kindLabel("postgresql")).toBe("PostgreSQL");
    expect(kindLabel("sqlite")).toBe("SQLite");
  });
});

describe("suggestionsFor", () => {
  const tables: SchemaTable[] = [
    { name: "orders", kind: "table", columns: [{ name: "id", type: "integer", primary_key: true }, { name: "status", type: "text", sample_values: ["a", "b"] }] },
    { name: "order_items", kind: "table", columns: [{ name: "id", type: "integer" }] },
    { name: "monthly", kind: "view", columns: [] },
  ];
  it("starts from saved questions, then the real tables", () => {
    expect(suggestionsFor(tables, ["Revenue by month"])).toEqual([
      "Revenue by month",
      "How many orders per status?",
      "How many order items are there?",
    ]);
  });
  it("offers at most four, without repeats", () => {
    expect(suggestionsFor(tables, ["a", "a", "b", "c", "d", "e"])).toHaveLength(4);
  });
});

describe("chartData", () => {
  it("keys rows by column, with the category as text and measures as numbers", () => {
    const data = chartData(["year", "hires", "avg"], [[2024, 3, "12.5"], [2025, null, 4]], { type: "line", x: "year", y: ["hires", "avg"] });
    expect(data).toEqual([
      { year: "2024", hires: 3, avg: 12.5 },
      { year: "2025", hires: 0, avg: 4 },
    ]);
  });
});

describe("dayRows", () => {
  it("fills every day of the span, splitting answered, refused and the rest", () => {
    const rows = dayRows(
      [{ day: "2026-06-14", questions: 5, answered: 3, refused: 1, failed: 1, executions: 3, rows_returned: 40, input_tokens: 0, output_tokens: 0 }],
      3,
      new Date(Date.UTC(2026, 5, 15)),
    );
    expect(rows.map((r) => r.questions)).toEqual([0, 5, 0]);
    expect(rows[1]).toMatchObject({ answered: 3, refused: 1, other: 1, rows: 40 });
  });
});
