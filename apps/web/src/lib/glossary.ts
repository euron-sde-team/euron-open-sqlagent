/** Plain-words explanations for SQLAgent vocabulary, shown as inline hints. */
export const GLOSSARY = {
  sqlGuard:
    "Before any query runs, SQLAgent parses it into a syntax tree and accepts it only if it is exactly one read-only SELECT: no writes, no schema changes, no second statement, no function with side effects.",
  readOnlyConnection:
    "The database session itself is opened read-only (PostgreSQL and MySQL read-only transactions, SQLite read-only mode), so even a query that slipped past the guard could not write.",
  validated: "The SQL guard accepted this query as one read-only SELECT before it ran.",
  rowLimit:
    "The most rows a result keeps. Rows past it are never fetched from the database, and the result says it was cut.",
  scanLimit:
    "Before running, SQLAgent asks the database's own planner how many rows the query would read. Above this limit the query is stopped and reported instead of run.",
  timeout: "Seconds a query may run. The database itself cancels it at this limit.",
  sampleValues:
    "With this on, the distinct values of short text columns (a status, a country) go into the prompt, so 'shipped orders' matches the real spelling. Off by default: they are real data.",
  followUp:
    "A follow-up sees the earlier questions of the conversation, their SQL and a summary of their results, so 'and last year?' changes only the time range.",
  template: "A saved question. With its SQL kept, running it again skips the model and runs the checked query as is.",
  provider:
    "The model that writes the SQL. Bring your own key for OpenAI, Anthropic, Gemini, Ollama or any OpenAI-compatible endpoint; the built-in mock needs none.",
  chart:
    "SQLAgent offers a chart when a result has one category and one or more numbers: a line over time, a pie for a few parts of a whole, bars otherwise.",
  apiKey:
    "For other applications, the SDK and the CLI. A key belongs to one project; its scopes say what it may do (read, ask questions and run SQL, manage connections).",
} as const;

export type GlossaryKey = keyof typeof GLOSSARY;
