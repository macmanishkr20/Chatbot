"""
Azure OpenAI client factory and helpers.
"""
import asyncio
import json
from functools import wraps

import tiktoken
from azure.identity.aio import DefaultAzureCredential, get_bearer_token_provider
from openai import AsyncAzureOpenAI, AzureOpenAI

from config import (
    AZURE_OPENAI_CHAT_API_VERSION,
    AZURE_OPENAI_CHAT_DEPLOYMENT,
    AZURE_OPENAI_EMBEDDING_DEPLOYMENT,
    AZURE_OPENAI_ENDPOINT,
    AZURE_OPENAI_KEY,
    AZURE_OPENAI_STOP_SEQUENCE,
    AZURE_OPENAI_SYSTEM_MESSAGE,
    AZURE_OPENAI_TEMPERATURE,
    AZURE_OPENAI_TOP_P,
    MAX_TOKENS,
    SHOULD_STREAM,
    USER_AGENT,
)

ERROR_CODES_TO_RETRY = [429, 500, 503]

# Parse comma-separated deployment lists from environment
_CHAT_DEPLOYMENTS = [d.strip() for d in AZURE_OPENAI_CHAT_DEPLOYMENT.split(",") if d.strip()]
_EMBED_DEPLOYMENTS = [d.strip() for d in AZURE_OPENAI_EMBEDDING_DEPLOYMENT.split(",") if d.strip()]

_DEFAULT_HEADERS = {"x-ms-useragent": USER_AGENT}


# ── Client Factory ──

def create_async_client(
    azure_endpoint: str = AZURE_OPENAI_ENDPOINT,
    azure_key: str = AZURE_OPENAI_KEY,
    llm_model: str = "",
) -> AsyncAzureOpenAI:
    """Create an async Azure OpenAI client."""
    if not azure_endpoint:
        raise ValueError("AZURE_OPENAI_ENDPOINT is required")

    token_provider = None
    if not azure_key:
        token_provider = get_bearer_token_provider(
            DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default"
        )

    return AsyncAzureOpenAI(
        api_version=AZURE_OPENAI_CHAT_API_VERSION,
        api_key=azure_key or None,
        azure_ad_token_provider=token_provider,
        default_headers=_DEFAULT_HEADERS,
        azure_endpoint=azure_endpoint,
    )


def create_sync_client(
    azure_endpoint: str = AZURE_OPENAI_ENDPOINT,
    azure_key: str = AZURE_OPENAI_KEY,
    llm_model: str = "",
) -> AzureOpenAI:
    """Create a sync Azure OpenAI client (used for embeddings)."""
    token_provider = None
    if not azure_key:
        token_provider = get_bearer_token_provider(
            DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default"
        )

    return AzureOpenAI(
        api_version=AZURE_OPENAI_CHAT_API_VERSION,
        api_key=azure_key or None,
        azure_ad_token_provider=token_provider,
        default_headers=_DEFAULT_HEADERS,
        azure_endpoint=azure_endpoint,
    )


# ── Model Args Builder ──

def parse_multi_columns(columns: str) -> list:
    if "|" in columns:
        return columns.split("|")
    return columns.split(",")


def prepare_model_args(
    request_messages,
    stream,
    use_data,
    tools,
    tool_choice,
    response_format,
    llm_model="",
) -> dict:
    messages = [{"role": "system", "content": AZURE_OPENAI_SYSTEM_MESSAGE}]

    for message in request_messages:
        if message:
            messages.append({"role": message["role"], "content": message["content"]})

    return {
        "messages": messages,
        "temperature": AZURE_OPENAI_TEMPERATURE,
        "max_tokens": MAX_TOKENS,
        "top_p": AZURE_OPENAI_TOP_P,
        "stop": (
            parse_multi_columns(AZURE_OPENAI_STOP_SEQUENCE)
            if AZURE_OPENAI_STOP_SEQUENCE
            else None
        ),
        "stream": stream and SHOULD_STREAM,
        "model": llm_model or AZURE_OPENAI_CHAT_DEPLOYMENT,
        "tools": tools if tools else None,
        "tool_choice": tool_choice if tool_choice else None,
        "response_format": {"type": response_format},
    }


# ── Model & Token Helpers ──

def get_llm_model(operation_name: str = "") -> str:
    """Return the primary chat deployment name."""
    return _CHAT_DEPLOYMENTS[0] if _CHAT_DEPLOYMENTS else ""


def get_embedding_model(operation_name: str = "") -> str:
    """Return the primary embedding deployment name."""
    return _EMBED_DEPLOYMENTS[0] if _EMBED_DEPLOYMENTS else ""


def get_model_info(llm_model: str) -> tuple[str, int]:
    return llm_model, 128000


def get_tokens_count(input_data, model_name: str) -> int:
    input_str = json.dumps(input_data) if input_data else ""
    try:
        tokenizer = tiktoken.encoding_for_model(model_name)
    except KeyError:
        tokenizer = tiktoken.get_encoding("cl100k_base")
    return len(tokenizer.encode(input_str))


# ── Retry Decorators ──

def retry_with_llm_backoff(base_delay: float = 1.0, max_retries: int = 3):
    """Async retry decorator for LLM calls with fallback across deployments."""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                status_code = getattr(e, "status_code", 0)
                code = getattr(e, "code", "")

                if status_code in ERROR_CODES_TO_RETRY or code == "context_length_exceeded":
                    kwargs_copy = {k: v for k, v in kwargs.items() if k != "llm_model"}
                    for _ in range(max_retries):
                        for llm_model in _CHAT_DEPLOYMENTS:
                            try:
                                return await func(*args, llm_model=llm_model, **kwargs_copy)
                            except Exception:
                                await asyncio.sleep(base_delay)
                    raise RuntimeError("LLM request failed for all models")
                raise

        return wrapper
    return decorator


def retry_with_embedding_backoff(base_delay: float = 1.0, max_retries: int = 3):
    """Sync retry decorator for embedding calls with fallback across deployments."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                status_code = getattr(e, "status_code", 0)
                code = getattr(e, "code", "")

                if status_code in ERROR_CODES_TO_RETRY or code == "context_length_exceeded":
                    kwargs_copy = {k: v for k, v in kwargs.items() if k != "embedding_model"}
                    import time
                    for _ in range(max_retries):
                        for embedding_model in _EMBED_DEPLOYMENTS:
                            try:
                                return func(*args, embedding_model=embedding_model, **kwargs_copy)
                            except Exception:
                                time.sleep(base_delay)
                    raise RuntimeError("Embedding request failed for all models")
                raise

        return wrapper
    return decorator
