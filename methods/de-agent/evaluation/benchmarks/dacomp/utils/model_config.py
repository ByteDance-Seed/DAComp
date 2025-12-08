#!/usr/bin/env python3

# API Configuration - Default
DEFAULT_BASE_URL = "xxxxx"
DEFAULT_API_VERSION = "2024-03-01-preview"
DEFAULT_API_KEY = "xxxxx"

# Supported models configuration
SUPPORTED_MODELS = {
    "gpt-4o-2024-11-20": {
        "max_tokens": 16000,
        "base_url": DEFAULT_BASE_URL,
        "api_key": DEFAULT_API_KEY,
        "api_version": DEFAULT_API_VERSION
    },
    "gpt-5-2025-08-07": {
        "max_tokens": 32000,
        "base_url": DEFAULT_BASE_URL,
        "api_key": DEFAULT_API_KEY,
        "api_version": DEFAULT_API_VERSION
    },
    "o3-2025-04-16": {
        "max_tokens": 32000,
        "base_url": DEFAULT_BASE_URL,
        "api_key": DEFAULT_API_KEY,
        "api_version": DEFAULT_API_VERSION
    },
    "gpt-oss-120b": {
        "max_tokens": 26000,
        "base_url": DEFAULT_BASE_URL,
        "api_key": DEFAULT_API_KEY,
        "api_version": DEFAULT_API_VERSION
    },
    "gemini-2.5-pro": {
        "max_tokens": 32000,
        "base_url": DEFAULT_BASE_URL,
        "api_key": DEFAULT_API_KEY,
        "api_version": DEFAULT_API_VERSION
    },
    "openai_qwen3-coder-plus": {
        "max_tokens": 26000,
        "base_url": DEFAULT_BASE_URL,
        "api_key": DEFAULT_API_KEY,
        "api_version": DEFAULT_API_VERSION
    },
    "openai_qwen3-235b-a22b": {
        "max_tokens": 16384,
        "base_url": DEFAULT_BASE_URL,
        "api_key": DEFAULT_API_KEY,
        "api_version": DEFAULT_API_VERSION
    },
    "openai_qwen3-30b-a3b": {
        "max_tokens": 16384,
        "base_url": DEFAULT_BASE_URL,
        "api_key": DEFAULT_API_KEY,
        "api_version": DEFAULT_API_VERSION
    },
    "openai_qwen3-8b": {
        "max_tokens": 8192,
        "base_url": DEFAULT_BASE_URL,
        "api_key": DEFAULT_API_KEY,
        "api_version": DEFAULT_API_VERSION
    },
    "openai_qwen3-4b": {
        "max_tokens": 32000,
        "base_url": DEFAULT_BASE_URL,
        "api_key": DEFAULT_API_KEY,
        "api_version": DEFAULT_API_VERSION
    },
    "kimi-k2-0905-preview": {
        "max_tokens": 32000,
        "base_url": DEFAULT_BASE_URL,
        "api_key": DEFAULT_API_KEY,
        "api_version": DEFAULT_API_VERSION
    },
    "Ark-kimi-k2-250711": {
        "max_tokens": 32000,
        "base_url": DEFAULT_BASE_URL,
        "api_key": DEFAULT_API_KEY,
        "api_version": DEFAULT_API_VERSION
    },
    "Ark-deepseek-v3.1-0821": {
        "max_tokens": 32000,
        "base_url": DEFAULT_BASE_URL,
        "api_key": DEFAULT_API_KEY,
        "api_version": DEFAULT_API_VERSION
    },
    "gcp-claude4-sonnet": {
        "max_tokens": 32000,
        "base_url": DEFAULT_BASE_URL,
        "api_key": DEFAULT_API_KEY,
        "api_version": DEFAULT_API_VERSION
    }
}

DEFAULT_MODEL = "gpt-4o-2024-11-20"

