"""The built-in deterministic provider: no network, no key, the same answer every time.

It lets a project work end to end before anyone configures a real model, and it is what
the test suites and the demo use. It is off for nothing and on for nobody by default: a
project gets it only when someone adds a provider of kind ``mock``.
"""

from __future__ import annotations

from sqlagent.providers.adapters.base import Adapter
from sqlagent.providers.mock.responder import respond
from sqlagent.providers.types import ModelRequest, ModelResponse, OnDelta, Usage


class MockAdapter(Adapter):
    async def complete(self, req: ModelRequest, on_delta: OnDelta | None = None) -> ModelResponse:
        system = "\n".join(m.content for m in req.messages if m.role == "system")
        turns: list[tuple[str, str]] = [
            (str(m.role), m.content) for m in req.messages if m.role != "system"
        ]
        text = respond(system, turns)
        if on_delta is not None:
            await on_delta(text)
        prompt_chars = sum(len(m.content) for m in req.messages)
        return ModelResponse(
            text=text,
            usage=Usage(
                input_tokens=max(prompt_chars // 4, 1), output_tokens=max(len(text) // 4, 1)
            ),
            model=req.model or "sqlagent-mock",
            usage_reported=False,
        )

    async def list_models(self) -> list[str]:
        return ["sqlagent-mock"]
