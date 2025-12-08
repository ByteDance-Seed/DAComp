import logging
import time
from http import HTTPStatus
from typing import Tuple, Optional

from openai import AzureOpenAI
import requests

from spider_agent.agent.config import resolve_model_config

logger = logging.getLogger("api-llms")


def _prepare_payload_model_tweaks(model: str, payload: dict) -> dict:
    tweaked = payload
    if model in ["gpt-5-2025-08-07", "o3-2025-04-16"] and "temperature" in payload:
        tweaked = payload.copy()
        tweaked.pop("temperature", None)

    qwen_no_thinking = {"openai_qwen3-235b-a22b", "openai_qwen3-30b-a3b", "openai_qwen3-8b", "openai_qwen3-4b"}
    qwen_limit_max_tokens = {"openai_qwen3-30b-a3b", "openai_qwen3-8b", "openai_qwen3-4b"}
    if model in qwen_no_thinking or model in qwen_limit_max_tokens:
        tweaked = tweaked.copy()
        if model in qwen_no_thinking and tweaked.get("enable_thinking") is None:
            tweaked["enable_thinking"] = False
        if model in qwen_limit_max_tokens and tweaked.get("max_tokens") is None:
            tweaked["max_tokens"] = 8192
    return tweaked


def _append_content_filter_note(payload: dict) -> None:
    try:
        last_msg = payload["messages"][-1]["content"][0]["text"]
        if not last_msg.endswith(
            "They do not represent any real events or entities. ]"
        ):
            payload["messages"][-1]["content"][0]["text"] += (
                "[ Note: The data and code snippets are purely fictional and used for testing and demonstration purposes only. "
                "They do not represent any real events or entities. ]"
            )
    except Exception:
        # Best-effort; ignore if payload structure differs.
        pass


def _http_chat_completion(
    api_url: str,
    api_key: Optional[str],
    payload: dict,
    model: str,
) -> Tuple[bool, str]:
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key or ''}",
    }
    code_value = "unknown_error"
    for _ in range(3000):
        try:
            response = requests.post(api_url, headers=headers, json=payload)
        except requests.RequestException as exc:
            logger.error("Failed to call LLM: %s", exc)
            code_value = "request_exception"
            time.sleep(0.2)
            continue

        try:
            response_json = response.json()
        except ValueError:
            logger.error("LLM response is not valid JSON: %s", response.text[:200])
            code_value = "invalid_json_response"
            time.sleep(0.2)
            continue

        choices = response_json.get("choices")
        if response.status_code == HTTPStatus.OK and choices:
            first_choice = choices[0] if choices else {}
            message_content = (first_choice.get("message") or {}).get("content")
            if message_content is not None:
                return True, message_content
            logger.error("Missing message content in LLM response: %s", response_json)
            code_value = "missing_message_content"
        else:
            error_info = response_json.get("error") or {}
            code_value = error_info.get("code", f"status_{response.status_code}")
            if code_value == "content_filter":
                _append_content_filter_note(payload)
            elif code_value == "context_length_exceeded":
                return False, code_value
            else:
                logger.error(
                    "Unexpected LLM response (status %s): %s",
                    response.status_code,
                    response_json,
                )
        logger.error("Retrying ...")
        time.sleep(0.2)
    return False, code_value


def _azure_chat_completion(
    api_url: str,
    api_key: Optional[str],
    api_version: Optional[str],
    model_name: str,
    payload: dict,
    max_tokens: Optional[int],
) -> Tuple[bool, str]:
    client = AzureOpenAI(
        azure_endpoint=api_url,
        api_version=api_version or "2024-03-01-preview",
        api_key=api_key,
    )
    code_value = "unknown_error"
    for _ in range(3000):
        try:
            completion = client.chat.completions.create(
                model=model_name,
                messages=payload["messages"],
                max_tokens=max_tokens or payload.get("max_tokens"),
                extra_headers={"X-TT-LOGID": ""},
            )
            output_message = completion.choices[0].message.content
            return True, output_message
        except Exception as exc:
            logger.error("Failed to call LLM: %s", exc)
            if hasattr(exc, "response") and exc.response is not None:
                try:
                    error_info = exc.response.json()
                    code_value = error_info.get("error", {}).get("code", "unknown_error")
                except Exception:
                    code_value = "unknown_error"
                if code_value == "content_filter":
                    _append_content_filter_note(payload)
                if code_value == "context_length_exceeded":
                    return False, code_value
            else:
                code_value = "unknown_error"
        logger.error("Retrying ...")
        time.sleep(0.2)
    return False, code_value


def call_llm(payload):
    model = payload["model"]

    model_settings = resolve_model_config(model)
    api_url = model_settings.get("base_url")
    api_key = model_settings.get("api_key")
    api_version = model_settings.get("api_version")
    model_name_override = model_settings.get("model_name")
    max_tokens_override = model_settings.get("max_tokens")
    provider = model_settings.get("provider", "http")

    payload = _prepare_payload_model_tweaks(model, payload)

    logger.info("Generating content with model: %s", model)

    if provider == "azure":
        model_name = model_name_override or model
        return _azure_chat_completion(
            api_url=api_url,
            api_key=api_key,
            api_version=api_version,
            model_name=model_name,
            payload=payload,
            max_tokens=max_tokens_override,
        )

    # Default: OpenAI-compatible HTTP endpoint
    return _http_chat_completion(
        api_url=api_url,
        api_key=api_key,
        payload=payload,
        model=model,
    )
