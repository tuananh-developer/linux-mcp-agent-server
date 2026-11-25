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
        if not isinstance(provider, str) or provider not in {"gemini", "openai", "openrouter", "anthropic", "ollama"}:
            raise AgentError("Nhà cung cấp AI không được hỗ trợ.")
        model = raw.get("model")
        if not isinstance(model, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}", model.strip()):
            raise AgentError("Model ID không hợp lệ.")
        model = model.strip()
        api_key = raw.get("api_key", "")
        if not isinstance(api_key, str) or len(api_key) > 1024 or any(ord(ch) < 32 for ch in api_key):
            raise AgentError("API key không hợp lệ.")
        api_key = api_key.strip()
        if provider != "ollama" and api_key and (
            not api_key.isascii() or any(ch.isspace() for ch in api_key)
        ):
            raise AgentError("API key phải là token ASCII không chứa khoảng trắng. Chỉ dán nội dung API key.")
        if provider != "ollama" and not api_key:
            raise AgentError("Nhà cung cấp này yêu cầu API key.")
        base_url = raw.get("base_url", "http://127.0.0.1:11434")
        if not isinstance(base_url, str) or len(base_url) > 256:
            raise AgentError("Ollama base URL không hợp lệ.")
        base_url = base_url.strip().rstrip("/")
        try:
            parsed = urlsplit(base_url)
        except ValueError:
            raise AgentError("Ollama base URL không hợp lệ.") from None
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
            "openrouter": "https://openrouter.ai/api/v1",
            "anthropic": "https://api.anthropic.com/v1",
            "ollama": self.settings.base_url,
        }[self.settings.provider]

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self.settings.provider == "gemini":
            headers["x-goog-api-key"] = self.settings.api_key
        elif self.settings.provider in {"openai", "openrouter"}:
            headers["Authorization"] = f"Bearer {self.settings.api_key}"
            if self.settings.provider == "openrouter":
                headers["HTTP-Referer"] = "https://mcp.home.arpa"
                headers["X-Title"] = "Linux Observatory"
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
            detail = ""
            try:
                error_body = json.loads(exc.read(16_384))
                if isinstance(error_body, dict):
                    provider_error = error_body.get("error")
                    if isinstance(provider_error, dict):
                        raw_detail = provider_error.get("message")
                        if isinstance(raw_detail, str):
                            detail = raw_detail
                    elif isinstance(provider_error, str):
                        detail = provider_error
            except (OSError, json.JSONDecodeError, UnicodeDecodeError):
                pass
            if self.settings.api_key and detail:
                detail = detail.replace(self.settings.api_key, "[đã ẩn]")
            detail = re.sub(r"\s+", " ", detail).strip()[:500]
            message = messages.get(exc.code, f"Nhà cung cấp AI trả về HTTP {exc.code}.")
            if exc.code == 400 and detail:
                message = f"{message} Chi tiết từ nhà cung cấp: {detail}"
            raise AgentError(message) from None
        except (URLError, TimeoutError, OSError):
            raise AgentError("Không thể kết nối nhà cung cấp AI. Kiểm tra mạng và cấu hình.") from None
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise AgentError("Nhà cung cấp AI trả về JSON không hợp lệ.") from None

    def _list_model_ids(self) -> list[str]:
        provider = self.settings.provider
        path = {
            "gemini": "/models",
            "openai": "/models",
            "openrouter": "/models",
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
        # OpenRouter's free router is a virtual model selector and may not
        # appear in /models. Put it before the display cap so a large catalog
        # cannot silently remove it. Also retain the selected catalog model
        # when it appears beyond the first 200 entries.
        if provider == "openrouter":
            if self.settings.model in model_ids:
                model_ids.remove(self.settings.model)
                model_ids.insert(0, self.settings.model)
            if "openrouter/free" in model_ids:
                model_ids.remove("openrouter/free")
            insert_at = 1 if model_ids and model_ids[0] == self.settings.model else 0
            model_ids.insert(insert_at, "openrouter/free")
        return model_ids[:200]

    async def test_connection(self) -> dict[str, Any]:
        model_ids = await asyncio.to_thread(self._list_model_ids)
        available = self.settings.model in model_ids
        provider_labels = {
            "gemini": "Google Gemini",
            "openai": "OpenAI",
            "openrouter": "OpenRouter",
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
    def _tool_call(
        name: str,
        arguments: object,
        call_id: str,
        provider_metadata: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        if not isinstance(arguments, dict):
            raise AgentError("Model trả về tham số tool không hợp lệ.")
        call: dict[str, Any] = {
            "id": call_id,
            "function": {"name": name, "arguments": arguments},
        }
        if provider_metadata:
            call["provider_metadata"] = provider_metadata
        return call

    def _chat_openai(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]],
    ) -> dict[str, Any]:
        wire_messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
        for index, message in enumerate(messages):
            role = message["role"]
            if role == "assistant":
                item: dict[str, Any] = {"role": "assistant", "content": message["content"] or None}
                message_metadata = message.get("provider_metadata", {})
                if (
                    self.settings.provider == "openrouter"
                    and isinstance(message_metadata, dict)
                    and isinstance(message_metadata.get("openrouter_reasoning_details"), list)
                ):
                    item["reasoning_details"] = message_metadata["openrouter_reasoning_details"]
                calls = []
                for call_index, call in enumerate(message.get("tool_calls", [])):
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
            "max_completion_tokens": 1536,
        }
        if self.settings.provider == "openrouter":
            # Only route to model providers that support every parameter in
            # this request. The free router already filters for tool calling;
            # require_parameters avoids endpoints silently rejecting options.
            payload["provider"] = {"require_parameters": True}
        else:
            payload["tool_choice"] = "auto"
            payload["parallel_tool_calls"] = False
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
        choices_raw = result.get("choices")
        if not isinstance(choices_raw, list):
            raise AgentError("OpenAI không trả về lựa chọn phản hồi.")
        choices = cast(list[Any], choices_raw)
        if not choices or not isinstance(choices[0], dict):
            raise AgentError("OpenAI không trả về lựa chọn phản hồi.")
        choice = cast(dict[str, Any], choices[0])
        message_raw = choice.get("message")
        if not isinstance(message_raw, dict):
            raise AgentError("OpenAI trả về message không hợp lệ.")
        message = cast(dict[str, Any], message_raw)
        content = message.get("content") or ""
        if not isinstance(content, str):
            content = ""
        calls: list[dict[str, Any]] = []
        raw_calls_value = message.get("tool_calls", [])
        if not isinstance(raw_calls_value, list):
            raise AgentError("OpenAI trả về tool call không hợp lệ.")
        raw_calls = cast(list[Any], raw_calls_value)
        if len(raw_calls) > 4:
            raise AgentError("OpenAI trả về quá nhiều tool call.")
        for index, raw_call in enumerate(raw_calls):
            if not isinstance(raw_call, dict) or not isinstance(raw_call.get("function"), dict):
                raise AgentError("OpenAI trả về tool call không hợp lệ.")
            raw_call = cast(dict[str, Any], raw_call)
            function = cast(dict[str, Any], raw_call["function"])
            raw_args = function.get("arguments", "{}")
            try:
                arguments = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
            except json.JSONDecodeError:
                raise AgentError("OpenAI trả về JSON arguments không hợp lệ.") from None
            calls.append(self._tool_call(
                str(function.get("name", "")),
                arguments,
                str(raw_call.get("id") or f"openai_{index}"),
            ))
        normalized_input: dict[str, Any] = {
            "role": "assistant",
            "content": content,
            "tool_calls": calls,
        }
        reasoning_details = message.get("reasoning_details")
        if (
            self.settings.provider == "openrouter"
            and isinstance(reasoning_details, list)
            and reasoning_details
        ):
            normalized_input["provider_metadata"] = {
                "openrouter_reasoning_details": reasoning_details
            }
        normalized = clean_messages([normalized_input])[0]
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
                for call in message.get("tool_calls", []):
                    function = call["function"]
                    part: dict[str, Any] = {"functionCall": {
                        "name": function["name"],
                        "args": function["arguments"],
                    }}
                    metadata = call.get("provider_metadata", {})
                    if isinstance(metadata, dict):
                        signature = metadata.get("gemini_thought_signature")
                        if isinstance(signature, str):
                            part["thoughtSignature"] = signature
                    parts.append(part)
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
        candidates_raw = result.get("candidates")
        if not isinstance(candidates_raw, list):
            raise AgentError("Gemini không trả về candidate.")
        candidates = cast(list[Any], candidates_raw)
        if not candidates or not isinstance(candidates[0], dict):
            raise AgentError("Gemini không trả về candidate.")
        candidate = cast(dict[str, Any], candidates[0])
        response_content_raw = candidate.get("content", {})
        if not isinstance(response_content_raw, dict):
            raise AgentError("Gemini trả về content không hợp lệ.")
        response_content = cast(dict[str, Any], response_content_raw)
        parts_raw = response_content.get("parts", [])
        if not isinstance(parts_raw, list):
            raise AgentError("Gemini trả về parts không hợp lệ.")
        parts = cast(list[Any], parts_raw)
        texts: list[str] = []
        calls: list[dict[str, Any]] = []
        for index, part_raw in enumerate(parts):
            if not isinstance(part_raw, dict):
                continue
            part = cast(dict[str, Any], part_raw)
            part_text = part.get("text")
            if isinstance(part_text, str):
                texts.append(part_text)
            function_raw = part.get("functionCall")
            if isinstance(function_raw, dict):
                function = cast(dict[str, Any], function_raw)
                function_name = function.get("name")
                if not isinstance(function_name, str):
                    raise AgentError("Gemini trả về function call không hợp lệ.")
                function_args: object = function.get("args", {})
                signature = part.get("thoughtSignature", part.get("thought_signature"))
                metadata = (
                    {"gemini_thought_signature": signature}
                    if isinstance(signature, str)
                    else None
                )
                calls.append(
                    self._tool_call(function_name, function_args, f"gemini_{index}", metadata)
                )
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
            payload["tools"] = [
                {
                    "name": item["function"]["name"],
                    "description": item["function"].get("description", ""),
                    "input_schema": item["function"].get(
                        "parameters", {"type": "object", "properties": {}}
                    ),
                }
                for item in tools
            ]
        result = self._request("POST", "/messages", payload)
        blocks_raw = result.get("content")
        if not isinstance(blocks_raw, list):
            raise AgentError("Anthropic không trả về content hợp lệ.")
        blocks = cast(list[Any], blocks_raw)
        texts: list[str] = []
        calls: list[dict[str, Any]] = []
        for index, block_raw in enumerate(blocks):
            if not isinstance(block_raw, dict):
                continue
            block = cast(dict[str, Any], block_raw)
            block_text = block.get("text")
            if block.get("type") == "text" and isinstance(block_text, str):
                texts.append(block_text)
            elif block.get("type") == "tool_use":
                function_name = block.get("name")
                if not isinstance(function_name, str):
                    raise AgentError("Anthropic trả về tool use không hợp lệ.")
                function_args: object = block.get("input", {})
                call_id = block.get("id")
                if not isinstance(call_id, str):
                    call_id = f"anthropic_{index}"
                calls.append(self._tool_call(function_name, function_args, call_id))
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
        raw_calls_value = message.get("tool_calls", [])
        if not isinstance(raw_calls_value, list):
            raise AgentError("Ollama trả về tool call không hợp lệ.")
        raw_calls = cast(list[Any], raw_calls_value)
        if len(raw_calls) > 4:
            raise AgentError("Ollama trả về quá nhiều tool call.")
        calls: list[dict[str, Any]] = []
        for index, raw_call_value in enumerate(raw_calls):
            if not isinstance(raw_call_value, dict):
                raise AgentError("Ollama trả về tool call không hợp lệ.")
            raw_call = cast(dict[str, Any], raw_call_value)
            function_raw = raw_call.get("function")
            if not isinstance(function_raw, dict):
                raise AgentError("Ollama trả về tool call không hợp lệ.")
            function = cast(dict[str, Any], function_raw)
            function_name = function.get("name")
            if not isinstance(function_name, str):
                raise AgentError("Ollama trả về tool call không hợp lệ.")
            function_args: object = function.get("arguments", {})
            call_id = raw_call.get("id")
            if not isinstance(call_id, str):
                call_id = f"ollama_{index}"
            calls.append(self._tool_call(function_name, function_args, call_id))
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
            elif self.settings.provider in {"openai", "openrouter"}:
                result = await asyncio.to_thread(self._chat_openai, messages, tools)
            elif self.settings.provider == "anthropic":
                result = await asyncio.to_thread(self._chat_anthropic, messages, tools)
            else:
                result = await asyncio.to_thread(self._chat_ollama, messages, tools)
        result["provider"] = self.settings.provider
        return result
