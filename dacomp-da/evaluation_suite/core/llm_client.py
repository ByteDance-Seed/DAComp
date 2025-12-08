from __future__ import annotations


from typing import List, Optional, Union
import time
import os
from types import SimpleNamespace

from loguru import logger
from openai import AzureOpenAI
from openai.types.chat.chat_completion_message import ChatCompletionMessage
from tenacity import retry, stop_after_attempt, wait_incrementing
import requests
import httpx

from .config import model_config

try:  # pragma: no cover
    from openai import RateLimitError
except Exception:  # pragma: no cover
    class RateLimitError(Exception):
        """Fallback RateLimitError if OpenAI SDK is unavailable."""
        pass


@retry(stop=stop_after_attempt(5), wait=wait_incrementing(4, 4))
def _openai_completion(
    base_url: str,
    api_key: Optional[str],
    messages: List[dict],
    model_name: str,
    api_version: Optional[str] = None,
    **generate_kwargs,
) -> Optional[ChatCompletionMessage]:
    timeout_seconds = 300
    http_client = httpx.Client(timeout=timeout_seconds, follow_redirects=True)
    client = AzureOpenAI(
        api_version=api_version or "2023-03-15-preview",
        azure_endpoint=base_url,
        api_key=api_key,
        timeout=timeout_seconds,
        http_client=http_client,
    )
    completion = None
    max_rate_retries = 500
    for attempt in range(1, max_rate_retries + 1):
        try:
            completion = client.chat.completions.create(
                messages=messages,  # type: ignore[arg-type]
                model=model_name,
                **generate_kwargs,
            )
            break
        except RateLimitError:
            if attempt == max_rate_retries:
                logger.error(
                    f"Rate limit reached for model {model_name}; "
                    f"giving up after {attempt} attempts."
                )
                raise
            logger.warning(
                f"Rate limit reached for model {model_name}; "
                f"retrying in 1s (attempt {attempt}/{max_rate_retries})."
            )
            time.sleep(1)

    if completion is None:
        return None
    try:
        return completion.choices[0].message
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"OpenAI completion failed: {exc}")
        return None


def llm_completion(
    messages: Union[str, List[dict]],
    model_config_name: str = "default_eval_config",
) -> Optional[ChatCompletionMessage]:
    if isinstance(messages, str):
        messages = [{"role": "user", "content": messages}]

    assert (
        model_config_name in model_config
    ), f"model_config_name {model_config_name} not found."

    config = model_config[model_config_name]
    model_name = config["model_name"]
    base_url = config["base_url"]
    api_key = config["api_key"]
    api_version = config.get("api_version")
    provider = config.get("provider", "openai")
    generate_kwargs = config.get("generate_kwargs", {})

    logger.debug(
        "Calling model",
        model_config=model_config_name,
        model_name=model_name,
    )

    if provider in {"http", "custom_http"}:
        return _http_completion(
            base_url=base_url,
            api_key=api_key,
            messages=messages,
            model_name=model_name,
            **generate_kwargs,
        )

    return _openai_completion(
        base_url=base_url,
        api_key=api_key,
        messages=messages,
        model_name=model_name,
        api_version=api_version,
        **generate_kwargs,
    )


def _prepare_payload_model_tweaks(model: str, payload: dict) -> dict:
    if model in ["gpt-5-2025-08-07", "o3-2025-04-16"] and "temperature" in payload:
        payload = payload.copy()
        payload.pop("temperature", None)

    qwen_no_thinking = {"openai_qwen3-235b-a22b", "openai_qwen3-30b-a3b", "openai_qwen3-8b", "openai_qwen3-4b"}
    qwen_limit_max_tokens = {"openai_qwen3-30b-a3b", "openai_qwen3-8b", "openai_qwen3-4b"}
    if model in qwen_no_thinking or model in qwen_limit_max_tokens:
        payload = payload.copy()
        if model in qwen_no_thinking and payload.get("enable_thinking") is None:
            payload["enable_thinking"] = False
        if model in qwen_limit_max_tokens and payload.get("max_tokens") is None:
            payload["max_tokens"] = 8192
    return payload


@retry(stop=stop_after_attempt(5), wait=wait_incrementing(4, 4))
def _http_completion(
    base_url: str,
    api_key: Optional[str],
    messages: List[dict],
    model_name: str,
    **generate_kwargs,
) -> Optional[ChatCompletionMessage]:
    base_url = os.environ.get("API_URL") or base_url
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key or ''}",
    }
    payload = {
        "model": model_name,
        "messages": messages,
    }
    payload.update(generate_kwargs)
    payload = _prepare_payload_model_tweaks(model_name, payload)

    # Match agent behavior: retry with logging
    for attempt in range(1, 3001):
        try:
            response = requests.post(
                base_url,
                headers=headers,
                json=payload,
                timeout=60,
            )
        except requests.RequestException as exc:
            logger.error("Failed to call model {}: {}", model_name, exc)
            time.sleep(0.2)
            continue

        try:
            response_json = response.json()
        except ValueError:
            logger.error(
                "LLM response is not valid JSON: {}", response.text[:200]
            )
            time.sleep(0.2)
            continue

        choices = response_json.get("choices")
        if response.status_code == 200 and choices:
            first_choice = choices[0] if choices else {}
            message = first_choice.get("message") or {}
            message_content = message.get("content")
            role = message.get("role", "assistant")
            if message_content is not None:
                return SimpleNamespace(role=role, content=message_content)
            logger.error(
                "Missing message content in LLM response: {}", response_json
            )
        else:
            error_info = response_json.get("error") or {}
            code_value = error_info.get("code", f"status_{response.status_code}")
            if code_value == "context_length_exceeded":
                return None
            logger.error(
                "Unexpected LLM response (status {}): {}",
                response.status_code,
                response_json,
            )
        logger.error("Retrying ...")
        time.sleep(0.2)

    return None
