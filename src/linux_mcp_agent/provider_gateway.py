"""Ephemeral, per-request adapters for user-selected AI providers.

Provider API keys are accepted in the request body, used only for that request,
never written to environment variables, files, logs, or persistent storage.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from typing import Any, cast
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from linux_mcp_agent.agent import SYSTEM_PROMPT, AgentError, clean_messages


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(
        self, req: Request, fp: Any, code: int, msg: str, headers: Any, newurl: str,
    ) -> None:
        return None


@dataclass(frozen=True)
class ProviderSettings:
    provider: str
    model: str
    api_key: str = field(default="", repr=False)
    base_url: str = "http://127.0.0.1:11434"

    @classmethod
    def from_payload(cls, raw: object) -> ProviderSettings:
        if not isinstance(raw, dict):
            raise AgentError("Chưa có cấu hình nhà cung cấp AI.")
        raw = cast(dict[str, Any], raw)
        provider = raw.get("provider")
        if provider not in {"gemini", "openai", "anthropic", "ollama"}:
            raise AgentError("Nhà cung cấp AI không được hỗ trợ.")
        model = raw.get("model")
        if not isinstance(model, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}", model.strip()):
            raise AgentError("Model ID không hợp lệ.")
        model = model.strip()
        api_key = raw.get("api_key", "")
        if not isinstance(api_key, str) or len(api_key) > 1024 or any(ord(ch) < 32 for ch in api_key):
            raise AgentError("API key không hợp lệ.")
        api_key = api_key.strip()
        if provider != "ollama" and not api_key:
            raise AgentError("Nhà cung cấp này yêu cầu API key.")
        base_url = raw.get("base_url", "http://127.0.0.1:11434")
        if not isinstance(base_url, str) or len(base_url) > 256:
            raise AgentError("Ollama base URL không hợp lệ.")
        base_url = base_url.strip().rstrip("/")
        parsed = urlsplit(base_url)
        if provider == "ollama":
            if (
                parsed.scheme != "http"
                or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
                or parsed.username
                or parsed.password
                or parsed.path
                or parsed.query
                or parsed.fragment
            ):
                raise AgentError("Ollama chỉ được phép dùng HTTP loopback trên máy chủ.")
        else:
            base_url = ""
        return cls(provider=provider, model=model, api_key=api_key, base_url=base_url)


class ProviderGateway:
    """One-request gateway; no provider credentials are retained after the request."""

    def __init__(self, settings: ProviderSettings) -> None:
        self.settings = settings
        self.opener = build_opener(ProxyHandler({}), _NoRedirect())
        self.limit = asyncio.Semaphore(1)

    @property
    def base_url(self) -> str:
        return {
            "gemini": "https://generativelanguage.googleapis.com/v1beta",
            "openai": "https://api.openai.com/v1",
            "anthropic": "https://api.anthropic.com/v1",
            "ollama": self.settings.base_url,
        }[self.settings.provider]

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self.settings.provider == "gemini":
            headers["x-goog-api-key"] = self.settings.api_key
        elif self.settings.provider == "openai":
            headers["Authorization"] = f"Bearer {self.settings.api_key}"
        elif self.settings.provider == "anthropic":
            headers["Authorization"] = f"Bearer {self.settings.api_key}"
            headers["anthropic-version"] = "2026-10-21"
        return headers

    def _request(
        self, method: str, path: str, payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
        request = Request(
            self.base_url + path,
            data=body,
            headers=self._headers(),
            method=method,
        )
        try:
            with self.opener.open(request, timeout=90 if payload else 12) as response:
                content = response.read(1_000_001)
            if len(content) > 1_000_000:
                raise AgentError("Phản hồi từ nhà cung cấp AI vượt quá giới hạn 1 MB.")
            result = json.loads(content)
            if not isinstance(result, dict):
                raise AgentError("Nhà cung cấp AI trả về dữ liệu không hợp lệ.")
            return cast(dict[str, Any], result)
        except HTTPError as exc:
            messages = {
                400: "Nhà cung cấp từ chối yêu cầu. Kiểm tra model và cấu hình tool calling.",
                401: "API key không hợp lệ hoặc đã hết hiệu lực.",
                403: "API key không có quyền dùng API hoặc model đã chọn.",
                404: "Không tìm thấy model hoặc endpoint. Kiểm tra Model ID.",
                408: "Nhà cung cấp xử lý quá thời gian.",
                429: "Đã chạm giới hạn quota hoặc tốc độ API. Kiểm tra billing và thử lại.",
            }
            raise AgentError(messages.get(exc.code, f"Nhà cung cấp AI trả về HTTP {exc.code}.")) from None
        except (URLError, TimeoutError, OSError):
            raise AgentError("Không thể kết nối nhà cung cấp AI. Kiểm tra mạng và cấu hình.") from None
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise AgentError("Nhà cung cấp AI trả về JSON không hợp lệ.") from None

    def _list_model_ids(self) -> list[str]:
        provider = self.settings.provider
        path = {
            "gemini": "/models",
            "openai": "/models",
            "anthropic": "/models",
            "ollama": "/api/tags",
        }[provider]
        result = self._request("GET", path)
        if provider == "ollama":
            entries = result.get("models", [])
        else:
            entries = result.get("models" if provider == "gemini" else "data", [])
        if not isinstance(entries, list):
            raise AgentError("Danh sách model từ nhà cung cấp không hợp lệ.")
        model_ids: list[str] = []
        for entry in cast(list[Any], entries):
            if not isinstance(entry, dict):
                continue
            raw_name = entry.get("name") if provider == "gemini" else entry.get("id")
            if provider == "ollama":
                raw_name = entry.get("name")
            if isinstance(raw_name, str):
                model_id = raw_name.removeprefix("models/")
                if provider != "gemini" or "generateContent" in entry.get("supportedGenerationMethods", []):
                    model_ids.append(model_id)
        return model_ids[:200]

    async def test_connection(self) -> dict[str, Any]:
        model_ids = await asyncio.to_thread(self._list_model_ids)
        available = self.settings.model in model_ids
        provider_labels = {
            "gemini": "Google Gemini",
            "openai": "OpenAI",
            "anthropic": "Anthropic",
            "ollama": "Ollama",
        }
        if available:
            message = "Đã xác thực API và tìm thấy model."
        else:
            message = "Kết nối API thành công nhưng không tìm thấy model đã chọn."
        return {
            "provider": self.settings.provider,
            "provider_label": provider_labels[self.settings.provider],
            "model": self.settings.model,
            "available": available,
            "message": message,
            "models": model_ids,
        }

    @staticmethod
    def _tool_defs(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "name": item["function"]["name"],
                "description": item["function"].get("description", ""),
                "parameters": item["function"].get("parameters", {"type": "object", "properties": {}}),
            }
            for item in tools
        ]

    @staticmethod
    def _tool_call(name: str, arguments: object, call_id: str) -> dict[str, Any]:
        if not isinstance(arguments, dict):
            raise AgentError("Model trả về tham số tool không hợp lệ.")
        return {
            "id": call_id,
            "function": {"name": name, "arguments": arguments},
        }

    def _chat_openai(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]],
    ) -> dict[str, Any]:
        wire_messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
        for index, message in enumerate(messages):
            role = message["role"]
            if role == "assistant":
                item: dict[str, Any] = {"role": "assistant", "content": message["content"] or None}
                calls = []
                for call in message.get("tool_calls", []):
                    function = call["function"]
                    calls.append({
                        "id": call.get("id") or f"call_{index}_{call_index}",
                        "type": "function",
                        "function": {"name": function["name"], "arguments": json.dumps(function["arguments"])},
                    })
                if calls:
                    item["tool_calls"] = calls
                wire_messages.append(item)
            elif role == "tool":
                wire_messages.append({
                    "role": "tool",
                    "tool_call_id": message.get("tool_call_id", f"call_{index}"),
                    "content": message["content"],
                })
            else:
                wire_messages.append({"role": "user", "content": message["content"]})
        payload: dict[str, Any] = {
            "model": self.settings.model,
            "messages": wire_messages,
            "max_tokens": 1536,
            "tool_choice": "auto",
            "parallel_tool_calls": False,
        }
        if tools:
            payload["tools"] = [
                {"type": "function", "function": {
                    "name": item["function"]["name"],
                    "description": item["function"].get("description", ""),
                    "parameters": item["function"].get("parameters", {"type": "object", "properties": {}}),
                }}
                for item in tools
            ]
        result = self._request("POST", "/chat/completions", payload)
        choices = result.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise AgentError("OpenAI không trả về lựa chọn phản hồi.")
        message = choices[0].get("message")
        if not isinstance(message, dict):
            raise AgentError("OpenAI trả về message không hợp lệ.")
        content = message.get("content") or ""
        if not isinstance(content, str):
            content = ""
        calls: list[dict[str, Any]] = []
        raw_calls = message.get("tool_calls", [])
        if not isinstance(raw_calls, list) or len(raw_calls) > 4:
            raise AgentError("OpenAI trả về quá nhiều tool call.")
        for index, raw_call in enumerate(raw_calls):
            if not isinstance(raw_call, dict) or not isinstance(raw_call.get("function"), dict):
                raise AgentError("OpenAI trả về tool call không hợp lệ.")
            function = cast(dict[str, Any], raw_call["function"])
            raw_args = function.get("arguments", "{}")
            try:
                arguments = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
            except json.JSONDecodeError:
                raise AgentError("OpenAI trả về JSON arguments không hợp lệ.") from None
            calls.append(self._tool_call(str(function.get("name", "")), arguments, str(raw_call.get("id") or f"openai_{index}")))
        normalized = clean_messages([{"role": "assistant", "content": content, "tool_calls": calls}])[0]
        usage = result.get("usage", {})
        if not isinstance(usage, dict):
            usage = {}
        return {
            "message": normalized,
            "model": self.settings.model,
            "usage": {"input_tokens": usage.get("prompt_tokens", 0), "output_tokens": usage.get("completion_tokens", 0)},
        }

    @staticmethod
    def _gemini_history(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        contents: list[dict[str, Any]] = []
        for message in messages:
            role = message["role"]
            if role == "user":
                contents.append({"role": "user", "parts": [{"text": message["content"]}]})
            elif role == "assistant":
                parts: list[dict[str, Any]] = []
                if message["content"]:
                    parts.append({"text": message["content"]})
                for call_index, call in enumerate(message.get("tool_calls", [])):
                    function = call["function"]
                    parts.append({"functionCall": {
                        "name": function["name"],
                        "args": function["arguments"],
                    }})
                contents.append({"role": "model", "parts": parts})
            else:
                try:
                    response = json.loads(message["content"])
                except (TypeError, json.JSONDecodeError):
                    response = {"text": str(message["content"])}
                if not isinstance(response, dict):
                    response = {"result": response}
                part = {"functionResponse": {"name": message["tool_name"], "response": response}}
                if contents and contents[-1].get("role") == "user" and contents[-1].get("_tool_results") is True:
                    cast(list[Any], contents[-1]["parts"]).append(part)
                else:
                    contents.append({"role": "user", "parts": [part], "_tool_results": True})
        for content in contents:
            content.pop("_tool_results", None)
        return contents

    def _chat_gemini(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]],
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
            "contents": self._gemini_history(messages),
            "generationConfig": {"maxOutputTokens": 1536, "temperature": 0.2},
        }
        if tools:
            payload["tools"] = [{"functionDeclarations": self._tool_defs(tools)}]
            payload["toolConfig"] = {"functionCallingConfig": {"mode": "AUTO"}}
        result = self._request(
            "POST", f"/models/{quote(self.settings.model, safe='')}:generateContent", payload,
        )
        candidates = result.get("candidates")
        if not isinstance(candidates, list) or not candidates or not isinstance(candidates[0], dict):
            raise AgentError("Gemini không trả về candidate.")
        candidate = candidates[0]
        response_content = candidate.get("content", {})
        if not isinstance(response_content, dict):
            raise AgentError("Gemini trả về content không hợp lệ.")
        parts = response_content.get("parts", [])
        if not isinstance(parts, list):
            raise AgentError("Gemini trả về parts không hợp lệ.")
        texts: list[str] = []
        calls: list[dict[str, Any]] = []
        for index, part in enumerate(parts):
            if not isinstance(part, dict):
                continue
            if isinstance(part.get("text"), str):
                texts.append(part["text"])
            function = part.get("functionCall")
            if isinstance(function, dict):
                calls.append(self._tool_call(
                    str(function.get("name", "")),
                    function.get("args", {}),
                    f"gemini_{index}",
                ))
        normalized = clean_messages([{
            "role": "assistant",
            "content": "\n".join(texts),
            "tool_calls": calls,
        }])[0]
        usage = result.get("usageMetadata", {})
        if not isinstance(usage, dict):
            usage = {}
        return {
            "message": normalized,
            "model": self.settings.model,
            "usage": {
                "input_tokens": usage.get("promptTokenCount", 0),
                "output_tokens": usage.get("candidatesTokenCount", 0),
            },
        }

    @staticmethod
    def _anthropic_history(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for index, message in enumerate(messages):
            role = message["role"]
            if role == "user":
                result.append({"role": "user", "content": message["content"]})
            elif role == "assistant":
                blocks: list[dict[str, Any]] = []
                if message["content"]:
                    blocks.append({"type": "text", "text": message["content"]})
                for call_index, call in enumerate(message.get("tool_calls", [])):
                    function = call["function"]
                    blocks.append({
                        "type": "tool_use",
                        "id": call.get("id") or f"anthropic_{index}_{call_index}",
                        "name": function["name"],
                        "input": function["arguments"],
                    })
                result.append({"role": "assistant", "content": blocks})
            else:
                tool_result = {
                    "type": "tool_result",
                    "tool_use_id": message.get("tool_call_id") or f"anthropic_{index}",
                    "content": message["content"],
                }
                if result and result[-1].get("role") == "user" and isinstance(result[-1].get("content"), list):
                    cast(list[Any], result[-1]["content"]).append(tool_result)
                else:
                    result.append({"role": "user", "content": [tool_result]})
        return result

    def _chat_anthropic(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]],
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.settings.model,
            "max_tokens": 1536,
            "system": SYSTEM_PROMPT,
            "messages": self._anthropic_history(messages),
        }
        if tools:
            payload["tools"] = self._tool_defs(tools)
        result = self._request("POST", "/messages", payload)
        blocks = result.get("content")
        if not isinstance(blocks, list):
            raise AgentError("Anthropic không trả về content hợp lệ.")
        texts: list[str] = []
        calls: list[dict[str, Any]] = []
        for index, block in enumerate(blocks):
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text" and isinstance(block.get("text"), str):
                texts.append(block["text"])
            elif block.get("type") == "tool_use":
                calls.append(self._tool_call(
                    str(block.get("name", "")),
                    block.get("input", {}),
                    str(block.get("id") or f"anthropic_{index}"),
                ))
        normalized = clean_messages([{
            "role": "assistant",
            "content": "\n".join(texts),
            "tool_calls": calls,
        }])[0]
        usage = result.get("usage", {})
        if not isinstance(usage, dict):
            usage = {}
        return {
            "message": normalized,
            "model": self.settings.model,
            "usage": {"input_tokens": usage.get("input_tokens", 0), "output_tokens": usage.get("output_tokens", 0)},
        }

    def _chat_ollama(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]],
    ) -> dict[str, Any]:
        wire_messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
        for index, message in enumerate(messages):
            role = message["role"]
            if role == "assistant":
                item: dict[str, Any] = {"role": "assistant", "content": message["content"]}
                calls = []
                for call_index, call in enumerate(message.get("tool_calls", [])):
                    function = call["function"]
                    calls.append({
                        "id": call.get("id") or f"ollama_{index}_{call_index}",
                        "function": {"name": function["name"], "arguments": function["arguments"]},
                    })
                if calls:
                    item["tool_calls"] = calls
                wire_messages.append(item)
            elif role == "tool":
                wire_messages.append({"role": "tool", "content": message["content"], "name": message["tool_name"]})
            else:
                wire_messages.append({"role": "user", "content": message["content"]})
        payload: dict[str, Any] = {
            "model": self.settings.model,
            "messages": wire_messages,
            "stream": False,
            "think": False,
            "options": {"temperature": 0.2, "num_predict": 1536},
        }
        if tools:
            payload["tools"] = [
                {"type": "function", "function": {
                    "name": item["function"]["name"],
                    "description": item["function"].get("description", ""),
                    "parameters": item["function"].get("parameters", {"type": "object", "properties": {}}),
                }}
                for item in tools
            ]
        result = self._request("POST", "/api/chat", payload)
        message = result.get("message")
        if not isinstance(message, dict):
            raise AgentError("Ollama không trả về message hợp lệ.")
        content = message.get("content", "")
        if not isinstance(content, str):
            content = ""
        raw_calls = message.get("tool_calls", [])
        if not isinstance(raw_calls, list) or len(raw_calls) > 4:
            raise AgentError("Ollama trả về quá nhiều tool call.")
        calls: list[dict[str, Any]] = []
        for index, raw_call in enumerate(raw_calls):
            if not isinstance(raw_call, dict) or not isinstance(raw_call.get("function"), dict):
                raise AgentError("Ollama trả về tool call không hợp lệ.")
            function = cast(dict[str, Any], raw_call["function"])
            calls.append(self._tool_call(
                str(function.get("name", "")),
                function.get("arguments", {}),
                str(raw_call.get("id") or f"ollama_{index}"),
            ))
        normalized = clean_messages([{"role": "assistant", "content": content, "tool_calls": calls}])[0]
        return {
            "message": normalized,
            "model": self.settings.model,
            "usage": {
                "input_tokens": result.get("prompt_eval_count", 0),
                "output_tokens": result.get("eval_count", 0),
            },
        }

    async def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
        if self.limit.locked():
            raise AgentError("AI đang xử lý yêu cầu khác. Vui lòng đợi.")
        async with self.limit:
            if self.settings.provider == "gemini":
                result = await asyncio.to_thread(self._chat_gemini, messages, tools)
            elif self.settings.provider == "openai":
                result = await asyncio.to_thread(self._chat_openai, messages, tools)
            elif self.settings.provider == "anthropic":
                result = await asyncio.to_thread(self._chat_anthropic, messages, tools)
            else:
                result = await asyncio.to_thread(self._chat_ollama, messages, tools)
        result["provider"] = self.settings.provider
        return result
