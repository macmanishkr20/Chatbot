"""Scorecard data-source factory (stub | sql)."""
from __future__ import annotations

import logging
from functools import lru_cache

from agents._base.sql_planner.data_source import AnalyticalDataSource
from core.config import SCORECARD_DATA_SOURCE_KIND

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_scorecard_data_source() -> AnalyticalDataSource:
    """Return the singleton Scorecard data source for the configured backend."""
    kind = SCORECARD_DATA_SOURCE_KIND
    logger.info("Scorecard data source: %s", kind)
    if kind == "stub":
        from agents.scorecard.data_sources.stub import StubScorecardDataSource
        return StubScorecardDataSource()
    if kind == "sql":
        from agents.scorecard.data_sources.sql import SQLScorecardDataSource
        return SQLScorecardDataSource()
    raise ValueError(
        f"Unknown SCORECARD_DATA_SOURCE_KIND={kind!r}. Valid values: 'stub', 'sql'."
    )
