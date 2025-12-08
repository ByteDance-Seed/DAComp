import os

# Example model configuration map for the public release. Replace the placeholder
# URLs, model names, and API keys with your own endpoints before running.
model_config = {
    "default_eval_config": {
        "provider": "openai",
        "model_name": "gpt-4o-mini",
        "base_url": "https://<your-azure-openai-resource>.openai.azure.com",
        "api_key": os.getenv("AZURE_OPENAI_API_KEY", "YOUR_API_KEY"),
        "api_version": "2024-08-01-preview",
        "generate_kwargs": {"max_tokens": 4096, "temperature": 0},
    },
    "gemini-2.5-flash": {
        "model_name": "gemini-2.5-flash",
        "base_url": "https://<your-azure-openai-resource>.openai.azure.com",
        "api_key": os.getenv("AZURE_OPENAI_API_KEY", "YOUR_API_KEY"),
        "api_version": "2024-08-01-preview",
        "generate_kwargs": {"max_tokens": 16384, "temperature": 0},
    },
    "example_vision_model": {
        "provider": "openai",
        "model_name": "gpt-4o",
        "base_url": "https://<your-azure-openai-resource>.openai.azure.com",
        "api_key": os.getenv("AZURE_OPENAI_API_KEY", "YOUR_API_KEY"),
        "api_version": "2024-08-01-preview",
        "generate_kwargs": {"max_tokens": 16384, "temperature": 0},
    },
    "example_http_model": {
        "provider": "http",  # OpenAI-compatible HTTP endpoint
        "model_name": "your-deployed-model",
        "base_url": "https://api.your-domain.com/v1/chat/completions",
        "api_key": os.getenv("CUSTOM_MODEL_API_KEY", "YOUR_API_KEY"),
        "generate_kwargs": {"max_tokens": 2048, "temperature": 0},
    },
}

VISION_CAPABLE_MODEL_CONFIGS = {
    "gemini-2.5-flash",
    "gpt-4.1-2025-04-14",
    "example_vision_model",
}
