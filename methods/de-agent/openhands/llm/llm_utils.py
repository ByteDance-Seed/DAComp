import copy
import json
from typing import TYPE_CHECKING, Any

from openhands.core.config import LLMConfig
from openhands.core.logger import openhands_logger as logger

if TYPE_CHECKING:
    from litellm import ChatCompletionToolParam

_SANITIZED_CACHE: dict[str, dict] = {}
_LOGGED_ONCE: set[str] = set()

def _log_once(tag: str, msg: str):
    if tag not in _LOGGED_ONCE:
        _LOGGED_ONCE.add(tag)
        logger.info(msg)

def _sanitize_schema_for_gemini(schema: Any) -> Any:
    if not isinstance(schema, dict):
        return schema

    for k in ("exclusiveMaximum", "exclusiveMinimum"):
        if k in schema:
            schema.pop(k, None)
            _log_once(f"rm:{k}", f'Removing unsupported key "{k}" in Gemini schema')

    if schema.get("type") == "string":
        fmt = schema.get("format")
        if fmt and fmt not in ("date-time",):
            _log_once(f"fmt:{fmt}", f'Removing unsupported format "{fmt}" for STRING in Gemini schema')
            schema.pop("format", None)

    for k in ("pattern", "multipleOf", "nullable", "const", "examples"):
        if k in schema:
            schema.pop(k, None)
            _log_once(f"rm:{k}", f'Removing unsupported key "{k}" in Gemini schema')

    props = schema.get("properties")
    if isinstance(props, dict):
        for name, sub in list(props.items()):
            props[name] = _sanitize_schema_for_gemini(sub)

    if "items" in schema:
        schema["items"] = _sanitize_schema_for_gemini(schema["items"])

    for k in ("anyOf", "oneOf", "allOf"):
        if isinstance(schema.get(k), list):
            schema[k] = [_sanitize_schema_for_gemini(s) for s in schema[k]]

    return schema


def check_tools(
    tools: list['ChatCompletionToolParam'], llm_config: LLMConfig
) -> list['ChatCompletionToolParam']:
    """Checks and modifies tools for compatibility with the current LLM."""
    if 'gemini' in llm_config.model.lower():
        _log_once(
            "gemini_sanitize_banner",
            f'Removing default fields and unsupported formats from tools for Gemini model {llm_config.model} '
            "since Gemini models have limited format support (only 'enum' and 'date-time' for STRING types)."
        )
        checked_tools = copy.deepcopy(tools)

        for tool in checked_tools:
            fn = tool.get('function')
            if not fn:
                continue
            params = fn.get('parameters')
            if not isinstance(params, dict):
                continue

            if 'properties' in params and isinstance(params['properties'], dict):
                for prop_name, prop in list(params['properties'].items()):
                    if isinstance(prop, dict):
                        if 'default' in prop:
                            del prop['default']
                        if prop.get('type') == 'string' and 'format' in prop:
                            supported_formats = ['enum', 'date-time']
                            fmt = prop['format']
                            if fmt not in supported_formats:
                                _log_once(f"fmt_prop:{fmt}", f'Removing unsupported format "{fmt}" for STRING parameter "{prop_name}"')
                                del prop['format']

            cache_key = None
            try:
                cache_key = json.dumps(params, sort_keys=True, ensure_ascii=False)
            except Exception:
                cache_key = None

            if cache_key and cache_key in _SANITIZED_CACHE:
                fn['parameters'] = copy.deepcopy(_SANITIZED_CACHE[cache_key])
            else:
                sanitized = _sanitize_schema_for_gemini(copy.deepcopy(params))
                fn['parameters'] = sanitized
                if cache_key:
                    _SANITIZED_CACHE[cache_key] = copy.deepcopy(sanitized)

        return checked_tools

    return tools

