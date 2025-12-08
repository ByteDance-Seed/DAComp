import copy
import os
import time
import warnings
from functools import partial
from typing import Any, Callable

import httpx
from types import SimpleNamespace

try:
    from openai import AzureOpenAI
    from openai import (
        BadRequestError as OpenAIBadRequestError,
        APIConnectionError as OpenAIAPIConnectionError,
        RateLimitError as OpenAIRateLimitError,
        APITimeoutError as OpenAIAPITimeoutError,
        APIStatusError as OpenAIAPIStatusError,
    )
except Exception:
    AzureOpenAI = None
    OpenAIBadRequestError = None
    OpenAIAPIConnectionError = None
    OpenAIRateLimitError = None
    OpenAIAPITimeoutError = None
    OpenAIAPIStatusError = None

from openhands.core.config import LLMConfig
from openhands.llm.metrics import Metrics

with warnings.catch_warnings():
    warnings.simplefilter('ignore')
    import litellm

from litellm import Message as LiteLLMMessage
from litellm import ModelInfo, PromptTokensDetails
from litellm import completion as litellm_completion
from litellm import completion_cost as litellm_completion_cost
from litellm.exceptions import (
    APIConnectionError,
    RateLimitError,
    ServiceUnavailableError,
)
from litellm.types.utils import CostPerToken, ModelResponse, Usage
from litellm.utils import create_pretrained_tokenizer

from openhands.core.exceptions import LLMNoResponseError
from openhands.core.logger import openhands_logger as logger
from openhands.core.message import Message
from openhands.llm.debug_mixin import DebugMixin
from openhands.llm.fn_call_converter import (
    STOP_WORDS,
    convert_fncall_messages_to_non_fncall_messages,
    convert_non_fncall_messages_to_fncall_messages,
)
from openhands.llm.retry_mixin import RetryMixin



__all__ = ['LLM']

# tuple of exceptions to retry on
LLM_RETRY_EXCEPTIONS: tuple[type[Exception], ...] = (
    APIConnectionError,
    RateLimitError,
    ServiceUnavailableError,
    litellm.Timeout,
    litellm.InternalServerError,
    LLMNoResponseError,
)

_openai_retry_excs = tuple(
    e for e in [
        OpenAIAPIConnectionError,
        OpenAIRateLimitError,
        OpenAIAPITimeoutError,
        OpenAIAPIStatusError,
    ] if e is not None
)
if _openai_retry_excs:
    LLM_RETRY_EXCEPTIONS = LLM_RETRY_EXCEPTIONS + _openai_retry_excs

# cache prompt supporting models
# remove this when we gemini and deepseek are supported
CACHE_PROMPT_SUPPORTED_MODELS = [
    'claude-3-7-sonnet-20250219',
    'claude-sonnet-3-7-latest',
    'claude-3.7-sonnet',
    'claude-3-5-sonnet-20241022',
    'claude-3-5-sonnet-20240620',
    'claude-3-5-haiku-20241022',
    'claude-3-haiku-20240307',
    'claude-3-opus-20240229',
    'claude-sonnet-4-20250514',
    'claude-sonnet-4',
    'claude-opus-4-20250514',
    'claude-opus-4-1-20250805',
]

# function calling supporting models
FUNCTION_CALLING_SUPPORTED_MODELS = [
    'claude-3-7-sonnet-20250219',
    'claude-sonnet-3-7-latest',
    'claude-3-5-sonnet',
    'claude-3-5-sonnet-20240620',
    'claude-3-5-sonnet-20241022',
    'claude-3.5-haiku',
    'claude-3-5-haiku-20241022',
    'claude-sonnet-4-20250514',
    'claude-sonnet-4',
    'claude-opus-4-20250514',
    'claude-opus-4-1-20250805',
    'gpt-4o-mini',
    'gpt-4o',
    'gpt-4o-2024-11-20',
    'o1-2024-12-17',
    'o3-mini-2025-01-31',
    'o3-mini',
    'o3',
    'o3-2025-04-16',
    'o4-mini',
    'o4-mini-2025-04-16',
    'gemini-2.5-pro',
    'gpt-4.1',
    'kimi-k2-0711-preview',
    'kimi-k2-instruct',
    'Qwen3-Coder-480B-A35B-Instruct',
    'qwen3-coder',  # this will match both qwen3-coder-480b (openhands provider) and qwen3-coder (for openrouter)
    'gpt-5',
    'gpt-5-2025-08-07',
]

REASONING_EFFORT_SUPPORTED_MODELS = [
    'o1-2024-12-17',
    'o1',
    'o3',
    'o3-2025-04-16',
    'o3-mini-2025-01-31',
    'o3-mini',
    'o4-mini',
    'o4-mini-2025-04-16',
    'gemini-2.5-flash',
    'gemini-2.5-pro',
    'gpt-5',
    'gpt-5-2025-08-07',
    'claude-opus-4-1-20250805',  # we need to remove top_p for opus 4.1
]

MODELS_WITHOUT_STOP_WORDS = [
    'o1-mini',
    'o1-preview',
    'o1',
    'o1-2024-12-17',
    'xai/grok-4-0709',
]

def _is_qwen3_openai_strict(model_name: str) -> bool:
    targets = {
        "openai_qwen3-235b-a22b",
        "openai_qwen3-30b-a3b",
        "openai_qwen3-8b",
        "openai_qwen3-4b",
    }
    return (model_name or "").lower() in targets


def _dict_to_attr(obj: Any) -> Any:
    if isinstance(obj, dict):
        return SimpleNamespace(**{k: _dict_to_attr(v) for k, v in obj.items()})
    if isinstance(obj, list):
        return [_dict_to_attr(i) for i in obj]
    return obj

class LLM(RetryMixin, DebugMixin):
    """The LLM class represents a Language Model instance.

    Attributes:
        config: an LLMConfig object specifying the configuration of the LLM.
    """

    def _sanitize_messages_for_provider(self, messages: list[dict]) -> list[dict]:
        sanitized = []
        for msg in messages:
            role = msg.get('role')
            content = msg.get('content')
            if role != 'user' and isinstance(content, list):
                parts = []
                for part in content:
                    if isinstance(part, dict) and part.get('type') in ('image_url','input_image','input_image_url'):
                        url = ''
                        iu = part.get('image_url')
                        if isinstance(iu, dict): url = iu.get('url') or ''
                        elif isinstance(iu, str): url = iu
                        url = url or part.get('url') or ''
                        parts.append(f"[image omitted: {url}]" if url else "[image omitted]")
                    elif isinstance(part, dict) and part.get('type') == 'text':
                        parts.append(part.get('text') or '')
                    else:
                        parts.append(str(part))
                msg = {**msg, 'content': "\n".join([p for p in parts if p is not None])}
            elif role != 'user' and isinstance(content, dict):
                if content.get('type') in ('image_url','input_image','input_image_url'):
                    iu = content.get('image_url')
                    url = iu.get('url') if isinstance(iu, dict) else (iu if isinstance(iu, str) else '')
                    url = url or content.get('url') or ''
                    msg = {**msg, 'content': f"[image omitted: {url}]" if url else "[image omitted]"}
                else:
                    msg = {**msg, 'content': str(content)}
            sanitized.append(msg)
        return sanitized

    def __init__(
        self,
        config: LLMConfig,
        service_id: str,
        metrics: Metrics | None = None,
        retry_listener: Callable[[int, int], None] | None = None,
    ) -> None:
        """Initializes the LLM. If LLMConfig is passed, its values will be the fallback.

        Passing simple parameters always overrides config.

        Args:
            config: The LLM configuration.
            metrics: The metrics to use.
        """
        self._tried_model_info = False
        self.cost_metric_supported: bool = True
        self.config: LLMConfig = copy.deepcopy(config)
        self.service_id = service_id
        self.metrics: Metrics = (
            metrics if metrics is not None else Metrics(model_name=config.model)
        )

        self.model_info: ModelInfo | None = None
        self.retry_listener = retry_listener
        if self.config.log_completions:
            if self.config.log_completions_folder is None:
                raise RuntimeError(
                    'log_completions_folder is required when log_completions is enabled'
                )
            os.makedirs(self.config.log_completions_folder, exist_ok=True)

        # call init_model_info to initialize config.max_output_tokens
        # which is used in partial function
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            self.init_model_info()
        if self.vision_is_active():
            logger.debug('LLM: model has vision enabled')
        if self.is_caching_prompt_active():
            logger.debug('LLM: caching prompt enabled')
        if self.is_function_calling_active():
            logger.debug('LLM: model supports function calling')

        # if using a custom tokenizer, make sure it's loaded and accessible in the format expected by litellm
        if self.config.custom_tokenizer is not None:
            self.tokenizer = create_pretrained_tokenizer(self.config.custom_tokenizer)
        else:
            self.tokenizer = None

        # set up the completion function
        kwargs: dict[str, Any] = {
            'temperature': self.config.temperature,
            'max_completion_tokens': self.config.max_output_tokens,
        }
        if self.config.top_k is not None:
            # openai doesn't expose top_k
            # litellm will handle it a bit differently than the openai-compatible params
            kwargs['top_k'] = self.config.top_k
        if self.config.top_p is not None:
            # openai doesn't expose top_p, but litellm does
            kwargs['top_p'] = self.config.top_p

        # Handle OpenHands provider - rewrite to litellm_proxy
        if self.config.model.startswith('openhands/'):
            model_name = self.config.model.removeprefix('openhands/')
            self.config.model = f'litellm_proxy/{model_name}'
            self.config.base_url = 'https://llm-proxy.app.all-hands.dev/'
            logger.debug(
                f'Rewrote openhands/{model_name} to {self.config.model} with base URL {self.config.base_url}'
            )

        if (
            self.config.model.lower() in REASONING_EFFORT_SUPPORTED_MODELS
            or self.config.model.split('/')[-1] in REASONING_EFFORT_SUPPORTED_MODELS
        ):
            # For Gemini models, only map 'low' to optimized thinking budget
            # Let other reasoning_effort values pass through to API as-is
            if 'gemini-2.5-pro' in self.config.model:
                logger.debug(
                    f'Gemini model {self.config.model} with reasoning_effort {self.config.reasoning_effort}'
                )
                if self.config.reasoning_effort in {None, 'low', 'none'}:
                    kwargs['thinking'] = {'budget_tokens': 128}
                    kwargs['allowed_openai_params'] = ['thinking']
                    kwargs.pop('reasoning_effort', None)
                else:
                    kwargs['reasoning_effort'] = self.config.reasoning_effort
                logger.debug(
                    f'Gemini model {self.config.model} with reasoning_effort {self.config.reasoning_effort} mapped to thinking {kwargs.get("thinking")}'
                )

            else:
                kwargs['reasoning_effort'] = self.config.reasoning_effort
            kwargs.pop(
                'temperature'
            )  # temperature is not supported for reasoning models
            kwargs.pop('top_p')  # reasoning model like o3 doesn't support top_p
        # Azure issue: https://github.com/All-Hands-AI/OpenHands/issues/6777
        if self.config.model.startswith('azure'):
            kwargs['max_tokens'] = self.config.max_output_tokens
            kwargs.pop('max_completion_tokens')

        # Add safety settings for models that support them
        if 'mistral' in self.config.model.lower() and self.config.safety_settings:
            kwargs['safety_settings'] = self.config.safety_settings
        elif 'gemini' in self.config.model.lower() and self.config.safety_settings:
            kwargs['safety_settings'] = self.config.safety_settings

        if hasattr(self.config, 'extra_headers') and self.config.extra_headers:
            kwargs['extra_headers'] = self.config.extra_headers

        if (self.config.custom_llm_provider or '').lower() == 'azure_raw':
            if AzureOpenAI is None:
                raise RuntimeError("cannot use custom_llm_provider=azure_raw。please install: poetry add 'openai>=1.0.0'")
            def _azure_raw_completion_unwrapped(*_args: Any, **_kwargs: Any):
                client = AzureOpenAI(
                    azure_endpoint=self.config.base_url,
                    api_key=(self.config.api_key.get_secret_value() if self.config.api_key else None),
                    api_version=(self.config.api_version or "2023-05-15"),
                )

                allowed = {
                    'messages',
                    'temperature',
                    'max_tokens',
                    'top_p',
                    'stop',
                    'tools',
                    'tool_choice',
                    'response_format',
                    'extra_body',
                }
                payload = {k: v for k, v in _kwargs.items() if k in allowed}

                incoming_extra_body = payload.pop('extra_body', None)
                extra_body_payload: dict[str, Any] = {}
                if isinstance(incoming_extra_body, dict):
                    extra_body_payload.update(incoming_extra_body)

                if _is_qwen3_openai_strict(self.config.model):
                    extra_body_payload.setdefault('stream', False)
                    extra_body_payload.setdefault('enable_thinking', False)

                if 'temperature' not in payload and self.config.temperature is not None:
                    payload['temperature'] = self.config.temperature
                if 'max_tokens' not in payload and self.config.max_output_tokens is not None:
                    payload['max_tokens'] = self.config.max_output_tokens
                if 'top_p' not in payload and self.config.top_p is not None:
                    payload['top_p'] = self.config.top_p

                extra_headers = {}
                if getattr(self.config, "extra_headers", None):
                    extra_headers.update(self.config.extra_headers)
                if _kwargs.get("extra_headers"):
                    extra_headers.update(_kwargs["extra_headers"])
                if extra_headers:
                    payload["extra_headers"] = extra_headers

                req_timeout = _kwargs.get("timeout")
                if req_timeout is None:
                   req_timeout = self.config.timeout if self.config.timeout else 10

                call_kwargs: dict[str, Any] = dict(model=self.config.model, timeout=req_timeout, **payload)
                if extra_body_payload:
                    call_kwargs['extra_body'] = extra_body_payload


                try:
                    completion = client.chat.completions.create(**call_kwargs)
                except Exception as e:
                   msg = str(e)
                   prov = (self.config.custom_llm_provider or 'azure_raw')
                   model_name = self.config.model
                   if OpenAIBadRequestError is not None and isinstance(e, OpenAIBadRequestError):
                       if 'TLS handshake timeout' in msg or '-4201' in msg:
                           raise APIConnectionError(f'Azure TLS handshake timeout: {msg}', prov, model_name) from e
                   if OpenAIAPIConnectionError is not None and isinstance(e, OpenAIAPIConnectionError):
                       raise APIConnectionError(f'Azure API connection error: {msg}', prov, model_name) from e
                   if OpenAIAPITimeoutError is not None and isinstance(e, OpenAIAPITimeoutError):
                       raise APIConnectionError(f'Azure API timeout: {msg}', prov, model_name) from e
                   raise
                return completion.model_dump()

            self._completion_unwrapped = _azure_raw_completion_unwrapped
        else:
            # 默认：仍走 LiteLLM
            self._completion_unwrapped = partial(
                litellm_completion,
                model=self.config.model,
                api_key=self.config.api_key.get_secret_value()
                if self.config.api_key
                else None,
                base_url=self.config.base_url,
                api_version=self.config.api_version,
                custom_llm_provider=self.config.custom_llm_provider,
                timeout=self.config.timeout,
                drop_params=self.config.drop_params,
                seed=self.config.seed,
                **kwargs,
            )

        @self.retry_decorator(
                    num_retries=self.config.num_retries,
                    retry_exceptions=LLM_RETRY_EXCEPTIONS,
                    retry_min_wait=self.config.retry_min_wait,
                    retry_max_wait=self.config.retry_max_wait,
                    retry_multiplier=self.config.retry_multiplier,
                    retry_listener=self.retry_listener,
                )
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            """Wrapper for the completion function. Normalizes response to dict for internal processing,
            and returns an attribute-accessible object to callers (response.choices/response.id)."""
            from openhands.io import json

            messages_kwarg: list[dict[str, Any]] | dict[str, Any] = []
            mock_function_calling = not self.is_function_calling_active()

            # Support positional args (model, messages, ...)
            if len(args) > 1:
                messages_kwarg = args[1] if len(args) > 1 else args[0]
                kwargs['messages'] = messages_kwarg
                args = args[2:]
            elif 'messages' in kwargs:
                messages_kwarg = kwargs['messages']

            # Ensure messages is a list
            messages: list[dict[str, Any]] = (
                messages_kwarg if isinstance(messages_kwarg, list) else [messages_kwarg]
            )

            # Convert to non-function-calling prompts when mocking
            original_fncall_messages = copy.deepcopy(messages)
            mock_fncall_tools = None
            if mock_function_calling and 'tools' in kwargs:
                add_in_context_learning_example = True
                if (
                    'openhands-lm' in self.config.model
                    or 'devstral' in self.config.model
                ):
                    add_in_context_learning_example = False

                messages = convert_fncall_messages_to_non_fncall_messages(
                    messages,
                    kwargs['tools'],
                    add_in_context_learning_example=add_in_context_learning_example,
                )
                kwargs['messages'] = messages

                # Add stop words when supported
                if (
                    self.config.model not in MODELS_WITHOUT_STOP_WORDS
                    and not self.config.disable_stop_word
                ):
                    kwargs['stop'] = STOP_WORDS

                mock_fncall_tools = kwargs.pop('tools')
                if 'openhands-lm' in self.config.model:
                    kwargs['tool_choice'] = 'none'
                else:
                    kwargs.pop('tool_choice', None)

            if not messages:
                raise ValueError('The messages list is empty. At least one message is required.')

            messages = self._sanitize_messages_for_provider(messages)
            kwargs['messages'] = messages

            # Log prompt
            self.log_prompt(messages)

            # litellm param rewrite toggle
            litellm.modify_params = self.config.modify_params

            if 'litellm_proxy' not in self.config.model and (self.config.custom_llm_provider or '').lower() != 'azure_raw':
                kwargs.pop('extra_body', None)

            # Call provider
            start_time = time.time()
            with warnings.catch_warnings():
                warnings.filterwarnings('ignore', category=DeprecationWarning, module='httpx.*')
                warnings.filterwarnings(
                    'ignore', message=r'.*content=.*upload.*', category=DeprecationWarning
                )
                resp_raw: ModelResponse = self._completion_unwrapped(*args, **kwargs)

            # Normalize to dict for internal processing
            if isinstance(resp_raw, dict):
                resp_dict: dict[str, Any] = resp_raw
            else:
                resp_dict = getattr(resp_raw, "model_dump", lambda: vars(resp_raw))()

            # Record latency
            latency = time.time() - start_time
            response_id = resp_dict.get('id', 'unknown')
            self.metrics.add_response_latency(latency, response_id)

            non_fncall_response = copy.deepcopy(resp_dict)

            # If mocked function calling, convert back to fn-call shape
            if mock_function_calling and mock_fncall_tools is not None:
                choices = non_fncall_response.get('choices', [])
                if not choices or len(choices) < 1:
                    raise LLMNoResponseError(
                        'Response choices is less than 1 - This is only seen in Gemini models so far. Response: '
                        + str(non_fncall_response)
                    )

                non_fncall_response_message = choices[0].get('message', {})
                fn_call_messages_with_response = convert_non_fncall_messages_to_fncall_messages(
                    messages + [non_fncall_response_message],
                    mock_fncall_tools,
                )
                fn_call_response_message = fn_call_messages_with_response[-1]
                if not isinstance(fn_call_response_message, LiteLLMMessage):
                    fn_call_response_message = LiteLLMMessage(**fn_call_response_message)

                # Write back converted message
                resp_dict['choices'][0]['message'] = fn_call_response_message.model_dump()

            # Validate choices
            if not resp_dict.get('choices') or len(resp_dict['choices']) < 1:
                raise LLMNoResponseError(
                    'Response choices is less than 1 - This is only seen in Gemini models so far. Response: '
                    + str(resp_dict)
                )

            # Log response (dict)
            self.log_response(resp_dict)

            # Post process for cost/usage (dict)
            cost = self._post_completion(resp_dict)

            # Optional raw completion logging
            if self.config.log_completions:
                assert self.config.log_completions_folder is not None
                log_file = os.path.join(
                    self.config.log_completions_folder,
                    f'{self.config.model.replace("/", "__")}-{time.time()}.json',
                )

                payload_to_log = {
                    'messages': messages,
                    'response': resp_dict if not mock_function_calling else non_fncall_response,
                    'args': args,
                    'kwargs': {k: v for k, v in kwargs.items() if k not in ('messages', 'client')},
                    'timestamp': time.time(),
                    'cost': cost,
                }
                if mock_function_calling:
                    payload_to_log['fncall_messages'] = original_fncall_messages
                    payload_to_log['fncall_response'] = resp_dict

                with open(log_file, 'w') as f:
                    f.write(json.dumps(payload_to_log))

            return _dict_to_attr(resp_dict)

        self._completion = wrapper

    @property
    def completion(self) -> Callable:
        """Decorator for the litellm completion function.

        Check the complete documentation at https://litellm.vercel.app/docs/completion
        """
        return self._completion

    def init_model_info(self) -> None:
        if self._tried_model_info:
            return
        self._tried_model_info = True
        try:
            if self.config.model.startswith('openrouter'):
                self.model_info = litellm.get_model_info(self.config.model)
        except Exception as e:
            logger.debug(f'Error getting model info: {e}')

        if self.config.model.startswith('litellm_proxy/'):
            # IF we are using LiteLLM proxy, get model info from LiteLLM proxy
            # GET {base_url}/v1/model/info with litellm_model_id as path param
            base_url = self.config.base_url.strip() if self.config.base_url else ''
            if not base_url.startswith(('http://', 'https://')):
                base_url = 'http://' + base_url

            response = httpx.get(
                f'{base_url}/v1/model/info',
                headers={
                    'Authorization': f'Bearer {self.config.api_key.get_secret_value() if self.config.api_key else None}'
                },
            )

            try:
                resp_json = response.json()
                if 'data' not in resp_json:
                    logger.info(
                        f'No data field in model info response from LiteLLM proxy: {resp_json}'
                    )
                all_model_info = resp_json.get('data', [])
            except Exception as e:
                logger.info(f'Error parsing JSON response from LiteLLM proxy: {e}')
                all_model_info = []
            current_model_info = next(
                (
                    info
                    for info in all_model_info
                    if info['model_name']
                    == self.config.model.removeprefix('litellm_proxy/')
                ),
                None,
            )
            if current_model_info:
                self.model_info = current_model_info['model_info']
                logger.debug(f'Got model info from litellm proxy: {self.model_info}')

        # Last two attempts to get model info from NAME
        if not self.model_info:
            try:
                self.model_info = litellm.get_model_info(
                    self.config.model.split(':')[0]
                )
            # noinspection PyBroadException
            except Exception:
                pass
        if not self.model_info:
            try:
                self.model_info = litellm.get_model_info(
                    self.config.model.split('/')[-1]
                )
            # noinspection PyBroadException
            except Exception:
                pass
        from openhands.io import json

        logger.debug(
            f'Model info: {json.dumps({"model": self.config.model, "base_url": self.config.base_url}, indent=2)}'
        )

        if self.config.model.startswith('huggingface'):
            # HF doesn't support the OpenAI default value for top_p (1)
            logger.debug(
                f'Setting top_p to 0.9 for Hugging Face model: {self.config.model}'
            )
            self.config.top_p = 0.9 if self.config.top_p == 1 else self.config.top_p

        # Set max_input_tokens from model info if not explicitly set
        if (
            self.config.max_input_tokens is None
            and self.model_info is not None
            and 'max_input_tokens' in self.model_info
            and isinstance(self.model_info['max_input_tokens'], int)
        ):
            self.config.max_input_tokens = self.model_info['max_input_tokens']

        # Set max_output_tokens from model info if not explicitly set
        if self.config.max_output_tokens is None:
            # Special case for Claude 3.7 Sonnet models
            if any(
                model in self.config.model
                for model in ['claude-3-7-sonnet', 'claude-3.7-sonnet']
            ):
                self.config.max_output_tokens = 64000  # litellm set max to 128k, but that requires a header to be set
            # Try to get from model info
            elif self.model_info is not None:
                # max_output_tokens has precedence over max_tokens
                if 'max_output_tokens' in self.model_info and isinstance(
                    self.model_info['max_output_tokens'], int
                ):
                    self.config.max_output_tokens = self.model_info['max_output_tokens']
                elif 'max_tokens' in self.model_info and isinstance(
                    self.model_info['max_tokens'], int
                ):
                    self.config.max_output_tokens = self.model_info['max_tokens']

        # Initialize function calling capability
        # Check if model name is in our supported list
        model_name_supported = (
            self.config.model in FUNCTION_CALLING_SUPPORTED_MODELS
            or self.config.model.split('/')[-1] in FUNCTION_CALLING_SUPPORTED_MODELS
            or any(m in self.config.model for m in FUNCTION_CALLING_SUPPORTED_MODELS)
        )

        # Handle native_tool_calling user-defined configuration
        if self.config.native_tool_calling is None:
            self._function_calling_active = model_name_supported
        else:
            self._function_calling_active = self.config.native_tool_calling

    def vision_is_active(self) -> bool:
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            return not self.config.disable_vision and self._supports_vision()

    def _supports_vision(self) -> bool:
        """Acquire from litellm if model is vision capable.

        Returns:
            bool: True if model is vision capable. Return False if model not supported by litellm.
        """
        # litellm.supports_vision currently returns False for 'openai/gpt-...' or 'anthropic/claude-...' (with prefixes)
        # but model_info will have the correct value for some reason.
        # we can go with it, but we will need to keep an eye if model_info is correct for Vertex or other providers
        # remove when litellm is updated to fix https://github.com/BerriAI/litellm/issues/5608
        # Check both the full model name and the name after proxy prefix for vision support
        return (
            litellm.supports_vision(self.config.model)
            or litellm.supports_vision(self.config.model.split('/')[-1])
            or (
                self.model_info is not None
                and self.model_info.get('supports_vision', False)
            )
        )

    def is_caching_prompt_active(self) -> bool:
        """Check if prompt caching is supported and enabled for current model.

        Returns:
            boolean: True if prompt caching is supported and enabled for the given model.
        """
        return (
            self.config.caching_prompt is True
            and (
                self.config.model in CACHE_PROMPT_SUPPORTED_MODELS
                or self.config.model.split('/')[-1] in CACHE_PROMPT_SUPPORTED_MODELS
            )
            # We don't need to look-up model_info, because only Anthropic models needs the explicit caching breakpoint
        )

    def is_function_calling_active(self) -> bool:
        """Returns whether function calling is supported and enabled for this LLM instance.

        The result is cached during initialization for performance.
        """
        return self._function_calling_active

    def _post_completion(self, response: ModelResponse) -> float:
        """Post-process the completion response.

        Logs the cost and usage stats of the completion call.
        """
        try:
            cur_cost = self._completion_cost(response)
        except Exception:
            cur_cost = 0

        stats = ''
        if self.cost_metric_supported:
            # keep track of the cost
            stats = 'Cost: %.2f USD | Accumulated Cost: %.2f USD\n' % (
                cur_cost,
                self.metrics.accumulated_cost,
            )

        # Add latency to stats if available
        if self.metrics.response_latencies:
            latest_latency = self.metrics.response_latencies[-1]
            stats += 'Response Latency: %.3f seconds\n' % latest_latency.latency

        usage: Usage | None = response.get('usage')
        response_id = response.get('id', 'unknown')

        if usage:
            # keep track of the input and output tokens
            prompt_tokens = usage.get('prompt_tokens', 0)
            completion_tokens = usage.get('completion_tokens', 0)

            if prompt_tokens:
                stats += 'Input tokens: ' + str(prompt_tokens)

            if completion_tokens:
                stats += (
                    (' | ' if prompt_tokens else '')
                    + 'Output tokens: '
                    + str(completion_tokens)
                    + '\n'
                )

            prompt_tokens_details = usage.get('prompt_tokens_details')
            cache_hit_tokens = 0
            if prompt_tokens_details:
                if isinstance(prompt_tokens_details, dict):
                    cache_hit_tokens = prompt_tokens_details.get('cached_tokens') or 0
                else:
                    cache_hit_tokens = getattr(prompt_tokens_details, 'cached_tokens', 0) or 0

            if cache_hit_tokens:
                stats += 'Input tokens (cache hit): ' + str(cache_hit_tokens) + '\n'

            # For Anthropic, the cache writes have a different cost than regular input tokens
            # but litellm doesn't separate them in the usage stats
            # we can read it from the provider-specific extra field
            model_extra = usage.get('model_extra', {})
            cache_write_tokens = model_extra.get('cache_creation_input_tokens', 0)
            if cache_write_tokens:
                stats += 'Input tokens (cache write): ' + str(cache_write_tokens) + '\n'

            # Get context window from model info
            context_window = 0
            if self.model_info and 'max_input_tokens' in self.model_info:
                context_window = self.model_info['max_input_tokens']
                logger.debug(f'Using context window: {context_window}')

            # Record in metrics
            # We'll treat cache_hit_tokens as "cache read" and cache_write_tokens as "cache write"
            self.metrics.add_token_usage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cache_read_tokens=cache_hit_tokens,
                cache_write_tokens=cache_write_tokens,
                context_window=context_window,
                response_id=response_id,
            )

        # log the stats
        if stats:
            logger.debug(stats)

        return cur_cost

    def get_token_count(self, messages: list[dict] | list[Message]) -> int:
        """Get the number of tokens in a list of messages. Use dicts for better token counting.

        Args:
            messages (list): A list of messages, either as a list of dicts or as a list of Message objects.

        Returns:
            int: The number of tokens.
        """
        # attempt to convert Message objects to dicts, litellm expects dicts
        if (
            isinstance(messages, list)
            and len(messages) > 0
            and isinstance(messages[0], Message)
        ):
            logger.info(
                'Message objects now include serialized tool calls in token counting'
            )
            # Assert the expected type for format_messages_for_llm
            assert isinstance(messages, list) and all(
                isinstance(m, Message) for m in messages
            ), 'Expected list of Message objects'

            # We've already asserted that messages is a list of Message objects
            # Use explicit typing to satisfy mypy
            messages_typed: list[Message] = messages  # type: ignore
            messages = self.format_messages_for_llm(messages_typed)

        # try to get the token count with the default litellm tokenizers
        # or the custom tokenizer if set for this LLM configuration
        try:
            return int(
                litellm.token_counter(
                    model=self.config.model,
                    messages=messages,
                    custom_tokenizer=self.tokenizer,
                )
            )
        except Exception as e:
            # limit logspam in case token count is not supported
            logger.error(
                f'Error getting token count for\n model {self.config.model}\n{e}'
                + (
                    f'\ncustom_tokenizer: {self.config.custom_tokenizer}'
                    if self.config.custom_tokenizer is not None
                    else ''
                )
            )
            return 0

    def _is_local(self) -> bool:
        """Determines if the system is using a locally running LLM.

        Returns:
            boolean: True if executing a local model.
        """
        if self.config.base_url is not None:
            for substring in ['localhost', '127.0.0.1', '0.0.0.0']:
                if substring in self.config.base_url:
                    return True
        elif self.config.model is not None:
            if self.config.model.startswith('ollama'):
                return True
        return False

    def _completion_cost(self, response: Any) -> float:
        """Calculate completion cost and update metrics with running total.

        Calculate the cost of a completion response based on the model. Local models are treated as free.
        Add the current cost into total cost in metrics.

        Args:
            response: A response from a model invocation.

        Returns:
            number: The cost of the response.
        """
        if not self.cost_metric_supported:
            return 0.0

        extra_kwargs = {}
        if (
            self.config.input_cost_per_token is not None
            and self.config.output_cost_per_token is not None
        ):
            cost_per_token = CostPerToken(
                input_cost_per_token=self.config.input_cost_per_token,
                output_cost_per_token=self.config.output_cost_per_token,
            )
            logger.debug(f'Using custom cost per token: {cost_per_token}')
            extra_kwargs['custom_cost_per_token'] = cost_per_token

        # try directly get response_cost from response
        _hidden_params = getattr(response, '_hidden_params', {})
        cost = _hidden_params.get('additional_headers', {}).get(
            'llm_provider-x-litellm-response-cost', None
        )
        if cost is not None:
            cost = float(cost)
            logger.debug(f'Got response_cost from response: {cost}')

        try:
            if cost is None:
                try:
                    cost = litellm_completion_cost(
                        completion_response=response, **extra_kwargs
                    )
                except Exception as e:
                    logger.debug(f'Error getting cost from litellm: {e}')

            if cost is None:
                _model_name = '/'.join(self.config.model.split('/')[1:])
                cost = litellm_completion_cost(
                    completion_response=response, model=_model_name, **extra_kwargs
                )
                logger.debug(
                    f'Using fallback model name {_model_name} to get cost: {cost}'
                )
            self.metrics.add_cost(float(cost))
            return float(cost)
        except Exception:
            self.cost_metric_supported = False
            logger.debug('Cost calculation not supported for this model.')
        return 0.0

    def __str__(self) -> str:
        if self.config.api_version:
            return f'LLM(model={self.config.model}, api_version={self.config.api_version}, base_url={self.config.base_url})'
        elif self.config.base_url:
            return f'LLM(model={self.config.model}, base_url={self.config.base_url})'
        return f'LLM(model={self.config.model})'

    def __repr__(self) -> str:
        return str(self)

    def format_messages_for_llm(self, messages: Message | list[Message]) -> list[dict]:
        if isinstance(messages, Message):
            messages = [messages]

        # set flags to know how to serialize the messages
        for message in messages:
            message.cache_enabled = self.is_caching_prompt_active()
            message.vision_enabled = self.vision_is_active()
            message.function_calling_enabled = self.is_function_calling_active()
            if 'deepseek' in self.config.model:
                message.force_string_serializer = True
            if 'kimi-k2-instruct' in self.config.model and 'groq' in self.config.model:
                message.force_string_serializer = True

        # let pydantic handle the serialization
        return [message.model_dump() for message in messages]
