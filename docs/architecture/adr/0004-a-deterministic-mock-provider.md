# 0004: A deterministic mock provider

**Status:** accepted

**Context.** Tests, the demo and the e2e suite must not depend on a vendor, a key or the
network, and must give the same answer every time.

**Decision.** A rule-based planner answers SQLAgent's own prompts by parsing the schema
block back out of them. It backs an in-process `mock` provider kind and the `mockai`
service, which speaks the OpenAI, Anthropic, Gemini and Ollama wire formats so every real
adapter is exercised over HTTP.

**Consequences.** Every acceptance criterion runs with no external provider. The planner
answers a bounded family of questions and says so honestly otherwise; it is not a substitute
for a real model in production.
