"""
Bootstrap: load .env BEFORE any submodule reads secrets.

This file is imported first by ``core/config/__init__.py`` so that
``load_dotenv`` runs before any submodule calls ``get_secret`` (which
falls back to env vars when VAULT_URL is not set).
"""
import logging
import os

from dotenv import load_dotenv

load_dotenv(override=True)

logger = logging.getLogger(__name__)

ENVIRONMENT = os.getenv("ENVIRONMENT")
logger.debug("ENVIRONMENT loaded: %s", ENVIRONMENT)
