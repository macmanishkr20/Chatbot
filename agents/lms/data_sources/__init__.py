"""
LMS data-source factory.

Reads ``core.config.LMS_DATA_SOURCE_KIND`` and returns the matching impl.
The returned object satisfies :class:`agents.lms.data_source.LMSDataSource`.

Adding a new backend:
  1. Create a new file in this package (e.g. ``grpc.py``) with a class that
     implements the LMSDataSource protocol.
  2. Add one elif branch below.
  3. Document the new value in core/config/runtime.py.

The factory is cached: one instance per process. Backends are expected to
be stateless / thread-safe (or to manage their own pools internally).
"""
from __future__ import annotations

import logging
from functools import lru_cache

from agents.lms.data_source import LMSDataSource
from core.config import LMS_DATA_SOURCE_KIND

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_lms_data_source() -> LMSDataSource:
    """Return the singleton LMSDataSource for the configured backend."""
    kind = LMS_DATA_SOURCE_KIND
    logger.info("LMS data source: %s", kind)

    if kind == "stub":
        from agents.lms.data_sources.stub import StubLMSDataSource
        return StubLMSDataSource()
    if kind == "http":
        from agents.lms.data_sources.http import HTTPLMSDataSource
        return HTTPLMSDataSource()
    if kind == "sql":
        from agents.lms.data_sources.sql import SQLLMSDataSource
        return SQLLMSDataSource()
    raise ValueError(
        f"Unknown LMS_DATA_SOURCE_KIND={kind!r}. "
        f"Valid values: 'stub', 'http', 'sql'."
    )
