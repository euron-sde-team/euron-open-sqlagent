"""OpenAI chat completions, also spoken by every OpenAI-compatible endpoint (vLLM, LM
Studio, Groq, Together, the Euri gateway, TokenShield, SmartRouter). ``base_url`` ends in
``/v1``."""

from __future__ import annotations

import json
from typing import Any

import httpx

from sqlagent.providers.adapters.base import (
    Adapter,
    call,
    raise_for_status,
    sse_events,
    transport_error,
)
from sqlagent.providers.types import (
    Message,
    ModelRequest,
    ModelResponse,
    OnDelta,
    ProviderError,
    Usage,
)


def to_wire(m: Message) -> dict[str, Any]:
    if m.role == "tool":
        return {"role": "tool", "tool_call_id": m.tool_call_id, "content": m.content}
    out: dict[str, Any] = {"role": m.role, "content": m.content}
    if m.tool_calls:
        out["tool_calls"] = [
            {
                "id": c.id,
                "type": "function",
                "function": {
                    "name": c.name,
                    "arguments": c.raw_arguments or json.dumps(c.arguments or {}),
                },
            }
            for c in m.tool_calls
        ]
        if not m.content:
            out["content"] = None
    return out


def payload(req: ModelRequest) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": req.model,
        "messages": [to_wire(m) for m in req.messages],
        "max_completion_tokens": req.max_tokens,
        "stream": req.stream,
    }
    if req.temperature is not None:
        body["temperature"] = req.temperature
    if req.tools:
        body["tools"] = [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in req.tools
        ]
        body["tool_choice"] = req.tool_choice
    if req.stream:
        body["stream_options"] = {"include_usage": True}
    return body


def _usage(raw: dict[str, Any] | None) -> Usage:
    raw = raw or {}
    details = raw.get("prompt_tokens_details") or {}
    return Usage(
        input_tokens=int(raw.get("prompt_tokens") or 0),
        output_tokens=int(raw.get("completion_tokens") or 0),
        cached_input_tokens=int(details.get("cached_tokens") or 0),
    )


def parse_response(body: dict[str, Any]) -> ModelResponse:
    choices = body.get("choices") or []
    if not choices:
        raise ProviderError("The provider returned no choices", retryable=True)
    msg = choices[0].get("message") or {}
    calls = [
        call(
            c.get("id") or f"call_{i}",
            (c.get("function") or {}).get("name", ""),
            (c.get("function") or {}).get("arguments"),
        )
        for i, c in enumerate(msg.get("tool_calls") or [])
    ]
    return ModelResponse(
        text=msg.get("content") or "",
        tool_calls=calls,
        usage=_usage(body.get("usage")),
        finish_reason=choices[0].get("finish_reason") or ("tool_calls" if calls else "stop"),
        model=body.get("model") or "",
        usage_reported=bool(body.get("usage")),
    )


class OpenAIAdapter(Adapter):
    def _headers(self) -> dict[str, str]:
        return {"authorization": f"Bearer {self.config.api_key}"} if self.config.api_key else {}

    async def list_models(self) -> list[str]:
        body = await self._get(f"{self.base}/models", self._headers())
        return sorted(
            str(m.get("id")) for m in body.get("data") or [] if isinstance(m, dict) and m.get("id")
        )

    async def complete(self, req: ModelRequest, on_delta: OnDelta | None = None) -> ModelResponse:
        if not req.stream:
            return parse_response(
                await self._post(f"{self.base}/chat/completions", payload(req), self._headers())
            )
        text: list[str] = []
        calls: dict[int, dict[str, str]] = {}
        out = ModelResponse(usage_reported=False)
        try:
            async with self.http.stream(
                "POST",
                f"{self.base}/chat/completions",
                json=payload(req),
                headers={**self.config.headers, **self._headers()},
                timeout=self.config.timeout_s,
            ) as resp:
                await raise_for_status(resp)
                async for _, data in sse_events(resp):
                    if data.strip() == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except ValueError as exc:
                        raise ProviderError(
                            "The provider sent a malformed stream event", retryable=True
                        ) from exc
                    if chunk.get("error"):
                        raise ProviderError(
                            str((chunk["error"] or {}).get("message", chunk["error"])),
                            retryable=True,
                        )
                    out.model = chunk.get("model") or out.model
                    if chunk.get("usage"):
                        out.usage = _usage(chunk["usage"])
                        out.usage_reported = True
                    for choice in chunk.get("choices") or []:
                        delta = choice.get("delta") or {}
                        if delta.get("content"):
                            text.append(delta["content"])
                            if on_delta:
                                await on_delta(delta["content"])
                        for tc in delta.get("tool_calls") or []:
                            slot = calls.setdefault(
                                int(tc.get("index", 0)), {"id": "", "name": "", "args": ""}
                            )
                            slot["id"] = tc.get("id") or slot["id"]
                            fn = tc.get("function") or {}
                            slot["name"] += fn.get("name") or ""
                            slot["args"] += fn.get("arguments") or ""
                        if choice.get("finish_reason"):
                            out.finish_reason = choice["finish_reason"]
        except httpx.HTTPError as exc:
            raise transport_error(exc) from exc
        out.text = "".join(text)
        out.tool_calls = [
            call(c["id"] or f"call_{i}", c["name"], c["args"]) for i, c in sorted(calls.items())
        ]
        if out.tool_calls and out.finish_reason == "stop":
            out.finish_reason = "tool_calls"
        return out
