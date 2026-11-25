"""OpenAI Responses adapter. Provider credentials never reach the browser or MCP."""

from __future__ import annotations

import asyncio
import json
from typing import Any, cast
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

from linux_mcp_agent.agent import (
    SYSTEM_PROMPT,
    AgentError,
    AgentSettings,
    LocalOnlyRedirect,
    clean_messages,
)


def response_input(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Translate the provider-neutral history, preserving every function-call identity."""
    items: list[dict[str, Any]] = []
    pending: dict[str, str] = {}
    for index, message in enumerate(messages):
        role = message["role"]
        if role in {"user", "assistant"}:
            if message["content"]:
                items.append({"role": role, "content": message["content"]})
            for call_index, call in enumerate(message.get("tool_calls", [])):
                function = call["function"]
                call_id = call.get("id") or f"call_{index}_{call_index}"
                if call_id in pending:
                    raise AgentError("Duplicate model tool-call ID")
                pending[call_id] = function["name"]
                items.append({"type": "function_call", "call_id": call_id,
                              "name": function["name"], "arguments": json.dumps(function["arguments"])})
        elif role == "tool":
            call_id = message.get("tool_call_id")
            if not call_id:
                call_id = next((key for key, name in pending.items() if name == message["tool_name"]), None)
            if not call_id or pending.get(call_id) != message["tool_name"]:
                raise AgentError("Tool result does not match an assistant call")
            del pending[call_id]
            items.append({"type": "function_call_output", "call_id": call_id, "output": message["content"]})
    if pending:
        raise AgentError("Missing tool result in conversation")
    return items


class OpenAIGateway:
    def __init__(self, settings: AgentSettings) -> None:
        self.settings = settings
        self.opener = build_opener(ProxyHandler({}), LocalOnlyRedirect())
        self.limit = asyncio.Semaphore(1)

    async def status(self) -> dict[str, Any]:
        configured = bool(self.settings.api_key)
        return {"enabled": True, "provider": "openai", "model": self.settings.model,
                "available": configured, "verified": False,
                "message": "API key configured; access verified on first request" if configured else "Set OPENAI_API_KEY in the server .env and restart"}

    def _request(self, payload: dict[str, Any]) -> dict[str, Any]:
        request = Request("https://api.openai.com/v1/responses", data=json.dumps(payload).encode(),
                          headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.settings.api_key}"})
        try:
            with self.opener.open(request, timeout=90) as response:
                content = response.read(1_000_001)
            if len(content) > 1_000_000:
                raise AgentError("OpenAI response exceeds size limit")
            result = json.loads(content)
            if not isinstance(result, dict):
                raise AgentError("Invalid OpenAI response")
            return cast(dict[str, Any], result)
        except HTTPError as exc:
            messages = {
                401: "OpenAI rejected the API key. Update OPENAI_API_KEY and restart the server.",
                403: "OpenAI API access denied. Check project/model access.",
                404: "OpenAI model not available to this project. Check OPENAI_MODEL.",
                429: "OpenAI quota or rate limit reached. Check API billing/credits and retry later.",
            }
            raise AgentError(messages.get(exc.code, f"OpenAI API request failed (HTTP {exc.code}). Check model and request configuration.")) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise AgentError("Cannot reach OpenAI API. Check Internet access and retry.") from exc
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise AgentError("OpenAI returned invalid JSON") from exc

    async def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
        if not self.settings.api_key:
            raise AgentError("Set OPENAI_API_KEY in the server .env and restart")
        if self.limit.locked():
            raise AgentError("AI is busy. Wait for the current answer to finish.")
        payload = {
            "model": self.settings.model, "instructions": SYSTEM_PROMPT,
            "input": response_input(messages), "store": False,
            "reasoning": {"effort": "none"},
            "max_output_tokens": self.settings.max_output_tokens,
            "parallel_tool_calls": False,
            "tools": [{"type": "function", "name": t["function"]["name"],
                       "description": t["function"]["description"],
                       "parameters": t["function"]["parameters"], "strict": False} for t in tools],
        }
        async with self.limit:
            result = await asyncio.to_thread(self._request, payload)
        if result.get("status") != "completed":
            raise AgentError("OpenAI did not complete the answer. Shorten the question or increase OPENAI_MAX_OUTPUT_TOKENS.")
        output = result.get("output")
        if not isinstance(output, list):
            raise AgentError("Invalid OpenAI output")
        text: list[str] = []
        calls: list[dict[str, Any]] = []
        for item in cast(list[Any], output):
            if not isinstance(item, dict):
                raise AgentError("Invalid OpenAI output item")
            item = cast(dict[str, Any], item)
            if item.get("type") == "function_call":
                try:
                    arguments = json.loads(item.get("arguments", "{}"))
                except (json.JSONDecodeError, TypeError) as exc:
                    raise AgentError("OpenAI returned invalid tool arguments") from exc
                calls.append({"id": item.get("call_id"), "function": {"name": item.get("name"), "arguments": arguments}})
            elif item.get("type") == "message":
                content = item.get("content")
                if not isinstance(content, list):
                    raise AgentError("Invalid OpenAI message content")
                for block in cast(list[Any], content):
                    if not isinstance(block, dict):
                        raise AgentError("Invalid OpenAI message block")
                    block = cast(dict[str, Any], block)
                    if block.get("type") in {"output_text", "refusal"}:
                        value = block.get("text") or block.get("refusal") or ""
                        if not isinstance(value, str):
                            raise AgentError("Invalid OpenAI text output")
                        text.append(value)
        normalized = clean_messages([{"role": "assistant", "content": "\n".join(text), "tool_calls": calls}])[0]
        return {"message": normalized, "model": self.settings.model, "provider": "openai",
                "usage": result.get("usage", {})}
