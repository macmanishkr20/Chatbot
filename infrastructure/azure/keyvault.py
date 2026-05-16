import os
import logging

# from azure.identity import ClientSecretCredential, DefaultAzureCredential
from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient

logger = logging.getLogger(__name__)

_client: SecretClient | None = None
_cache: dict[str, str] = {}


def _candidate_names(name: str) -> list[str]:
    values = [name, name.replace("_", "-"), name.replace("-", "_")]
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def _build_credential():
    env = os.getenv("ENVIRONMENT", "").upper()
    # tenant_id = os.getenv("AZURE_TENANT_ID", "").strip()  ###need to take it from keyvault
    client_id = os.getenv("AZURE_CLIENT_ID", "").strip()
    # client_secret = os.getenv("AZURE_CLIENT_SECRET", "").strip()
    

    # In PROD, prefer Managed Identity / Azure CLI chain.
    if env == "PROD":
        # return DefaultAzureCredential(
        #     exclude_environment_credential=True,
        #     managed_identity_client_id=(client_id or None),
        # )
        return DefaultAzureCredential()
    # if tenant_id and client_id and client_secret:
    #     logger.info(
    #         "Using ClientSecretCredential for Key Vault auth tenant_id=%s client_id=%s",
    #         tenant_id,
    #         client_id,
    #     )
    #     return ClientSecretCredential(
    #         tenant_id=tenant_id,
    #         client_id=client_id,
    #         client_secret=client_secret,
    #     )

    # return DefaultAzureCredential(managed_identity_client_id=(client_id or None))
    return DefaultAzureCredential()


def _get_client() -> SecretClient | None:
    global _client
    if _client is not None:
        return _client

    vault_url = os.getenv("VAULT_URL", "")
    if not vault_url:
        logger.warning("VAULT_URL (azure_key_vault_url) not set - falling back to .env values only.")
        return None

    credential = _build_credential()
    _client = SecretClient(vault_url=vault_url, credential=credential)
    logger.info("Key Vault client initialised for %s", vault_url)
    return _client


def get_secret(name: str, default: str = "") -> str:
    if name in _cache:
        return _cache[name]

    env = os.getenv("ENVIRONMENT", "PROD").upper()
    # env = "PROD"
    print(f"[LOG]----env---{env}---name---{name}")
    candidates = _candidate_names(name)

    # Local-first behavior for developers.
    if env == "LOCAL":
        for candidate in candidates:
            value = os.getenv(candidate, "")
            if value:
                _cache[name] = value
                print(f"[LOG]---Fetched secret '{value}' for '{name}' from environment variable '{candidate}'.")
                return value
        return default

    client = _get_client()
    print(f"[LOG]---client---{client}")
    if client is not None:
        for candidate in candidates:
            try:
                secret = client.get_secret(candidate)
                value = secret.value or default
                _cache[name] = value
                print(f"[LOG]---Fetched secret '{value}' from Key Vault.")
                return value
            except Exception:
                logger.debug("Secret '%s' not found in Key Vault.", candidate)

    # Do not silently read secrets from env in PROD.
    if env == "PROD":
        return default

    for candidate in candidates:
        value = os.getenv(candidate, "")
        if value:
            _cache[name] = value
            return value

    return default


def clear_cache() -> None:
    _cache.clear()


