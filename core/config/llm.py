"""LLM behavior: model deployments, sampling params, model maps."""
import json
import os

from infrastructure.azure.keyvault import get_secret

AZURE_OPENAI_MODEL = get_secret("AZURE-OPENAI-MODEL", "")

AZURE_OPENAI_MAX_TOKENS = int(get_secret("AZURE-OPENAI-MAX-TOKENS", "600"))
AZURE_OPENAI_TEMPERATURE = float(get_secret("AZURE-OPENAI-TEMPERATURE", "0.7"))
AZURE_OPENAI_TOP_P = float(get_secret("AZURE-OPENAI-TOP-P", "0.95"))
AZURE_OPENAI_STOP_SEQUENCE = os.getenv("AZURE-OPENAI-STOP-SEQUENCE", "")
AZURE_OPENAI_SYSTEM_MESSAGE = os.getenv(
    "AZURE-OPENAI-SYSTEM-MESSAGE",
    "You are a helpful assistant.",
)
SHOULD_STREAM = os.getenv("SHOULD-STREAM", "true").lower() == "true"

_models_raw = get_secret("AZURE-OPENAI-MODELS", "{}")
AZURE_OPENAI_MODELS: dict = json.loads(_models_raw) if _models_raw else {}

_prioritized_raw = get_secret("AZURE-OPENAI-MODELS-PRIORITIZED", "[]")
AZURE_OPENAI_MODELS_PRIORITIZED: list = json.loads(_prioritized_raw) if _prioritized_raw else []

_embed_prioritized_raw = get_secret("AZURE-OPENAI-EMBEDDING-MODELS-PRIORITIZED", "[]")
AZURE_OPENAI_EMBEDDING_MODELS_PRIORITIZED: list = (
    json.loads(_embed_prioritized_raw) if _embed_prioritized_raw else []
)

_token_limits_raw = get_secret("AZURE-OPENAI-TOKEN-LIMITS", "{}")
AZURE_OPENAI_TOKEN_LIMITS: dict = json.loads(_token_limits_raw) if _token_limits_raw else {}

# Generation token caps used by the response builder.
MAX_TOKENS = int(os.getenv("MAX-TOKENS", "1200"))
SNIPPET_CHARS = int(os.getenv("SNIPPET-CHARS", "800"))

# ── Groundedness verification (generate node) ──
# Min unigram overlap ratio for a citation to be considered grounded in source.
GROUNDEDNESS_THRESHOLD = float(os.getenv("GROUNDEDNESS_THRESHOLD", "0.25"))
