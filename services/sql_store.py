"""Azure SQL-backed BaseStore implementation for LangGraph cross-session memory."""

import json
from datetime import datetime, timezone
from typing import Any, Literal
from urllib.parse import quote_plus

from langgraph.store.base import (
    BaseStore,
    GetOp,
    Item,
    ListNamespacesOp,
    PutOp,
    SearchItem,
    SearchOp,
)

from sqlalchemy import Column, DateTime, MetaData, Table, Text, text
from sqlalchemy.dialects.mssql import NVARCHAR


class AzureSQLStore(BaseStore):
    """Async Azure SQL store for LangGraph long-term memory.

    Stores key-value items keyed by (namespace_tuple, key).
    Namespace tuples are stored as dot-separated strings.
    """

    TABLE_NAME = "langgraph_store"

    def __init__(self, connection_string: str, table_name: str | None = None):
        self.table_name = table_name or self.TABLE_NAME

        from sqlalchemy.ext.asyncio import (
            AsyncSession,
            async_sessionmaker,
            create_async_engine,
        )

        encoded = quote_plus(connection_string)
        self._engine = create_async_engine(
            f"mssql+aioodbc:///?odbc_connect={encoded}",
            pool_pre_ping=True,
            pool_recycle=300,
            pool_size=5,
            max_overflow=10,
        )
        self._session_factory = async_sessionmaker(
            self._engine, class_=AsyncSession, expire_on_commit=False
        )

        self._meta = MetaData()
        self._table = Table(
            self.table_name,
            self._meta,
            Column("namespace", NVARCHAR(500), primary_key=True),
            Column("key", NVARCHAR(500), primary_key=True),
            Column("value", Text, nullable=False),
            Column("created_at", DateTime, nullable=False),
            Column("updated_at", DateTime, nullable=False),
        )

    # ─── setup ──────────────────────────────────────────────

    async def asetup(self) -> None:
        """Create the store table if it doesn't exist."""
        async with self._engine.begin() as conn:
            await conn.run_sync(self._meta.create_all)

    # ─── helpers ────────────────────────────────────────────

    @staticmethod
    def _ns_to_str(namespace: tuple[str, ...]) -> str:
        return ".".join(namespace)

    @staticmethod
    def _str_to_ns(s: str) -> tuple[str, ...]:
        return tuple(s.split("."))

    def _row_to_item(self, row) -> Item:
        return Item(
            value=json.loads(row.value),
            key=row.key,
            namespace=self._str_to_ns(row.namespace),
            created_at=row.created_at.replace(tzinfo=timezone.utc),
            updated_at=row.updated_at.replace(tzinfo=timezone.utc),
        )

    # ─── async API ──────────────────────────────────────────

    async def aget(
        self,
        namespace: tuple[str, ...],
        key: str,
        *,
        refresh_ttl: bool | None = None,
    ) -> Item | None:
        ns = self._ns_to_str(namespace)
        async with self._session_factory() as session:
            result = await session.execute(
                text(
                    f"SELECT [namespace], [key], [value], [created_at], [updated_at] "
                    f"FROM {self.table_name} "
                    f"WHERE [namespace] = :ns AND [key] = :key"
                ),
                {"ns": ns, "key": key},
            )
            row = result.fetchone()
            return self._row_to_item(row) if row else None

    async def aput(
        self,
        namespace: tuple[str, ...],
        key: str,
        value: dict[str, Any],
        index: Literal[False] | list[str] | None = None,
        *,
        ttl: Any = None,
    ) -> None:
        ns = self._ns_to_str(namespace)
        val_json = json.dumps(value, default=str, ensure_ascii=False)
        async with self._session_factory() as session:
            existing = await session.execute(
                text(
                    f"SELECT 1 FROM {self.table_name} "
                    f"WHERE [namespace] = :ns AND [key] = :key"
                ),
                {"ns": ns, "key": key},
            )
            if existing.fetchone():
                await session.execute(
                    text(
                        f"UPDATE {self.table_name} "
                        f"SET [value] = :val, [updated_at] = GETUTCDATE() "
                        f"WHERE [namespace] = :ns AND [key] = :key"
                    ),
                    {"ns": ns, "key": key, "val": val_json},
                )
            else:
                await session.execute(
                    text(
                        f"INSERT INTO {self.table_name} "
                        f"([namespace], [key], [value], [created_at], [updated_at]) "
                        f"VALUES (:ns, :key, :val, GETUTCDATE(), GETUTCDATE())"
                    ),
                    {"ns": ns, "key": key, "val": val_json},
                )
            await session.commit()

    async def asearch(
        self,
        namespace_prefix: tuple[str, ...],
        /,
        *,
        query: str | None = None,
        filter: dict[str, Any] | None = None,
        limit: int = 10,
        offset: int = 0,
        refresh_ttl: bool | None = None,
    ) -> list[SearchItem]:
        prefix = self._ns_to_str(namespace_prefix)
        async with self._session_factory() as session:
            result = await session.execute(
                text(
                    f"SELECT [namespace], [key], [value], [created_at], [updated_at] "
                    f"FROM {self.table_name} "
                    f"WHERE [namespace] LIKE :prefix "
                    f"ORDER BY [updated_at] DESC "
                    f"OFFSET :offset ROWS FETCH NEXT :limit ROWS ONLY"
                ),
                {"prefix": prefix + "%", "offset": offset, "limit": limit},
            )
            rows = result.fetchall()
            return [
                SearchItem(
                    value=json.loads(r.value),
                    key=r.key,
                    namespace=self._str_to_ns(r.namespace),
                    created_at=r.created_at.replace(tzinfo=timezone.utc),
                    updated_at=r.updated_at.replace(tzinfo=timezone.utc),
                    score=None,
                )
                for r in rows
            ]

    async def adelete(self, namespace: tuple[str, ...], key: str) -> None:
        ns = self._ns_to_str(namespace)
        async with self._session_factory() as session:
            await session.execute(
                text(
                    f"DELETE FROM {self.table_name} "
                    f"WHERE [namespace] = :ns AND [key] = :key"
                ),
                {"ns": ns, "key": key},
            )
            await session.commit()

    async def alist_namespaces(
        self,
        *,
        prefix: tuple[str, ...] | None = None,
        suffix: tuple[str, ...] | None = None,
        max_depth: int | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[tuple[str, ...]]:
        async with self._session_factory() as session:
            q = (
                f"SELECT DISTINCT [namespace] FROM {self.table_name} "
                f"WHERE 1=1 "
            )
            params: dict[str, Any] = {}
            if prefix:
                q += "AND [namespace] LIKE :prefix "
                params["prefix"] = self._ns_to_str(prefix) + "%"
            if suffix:
                q += "AND [namespace] LIKE :suffix "
                params["suffix"] = "%" + self._ns_to_str(suffix)
            q += "ORDER BY [namespace] OFFSET :offset ROWS FETCH NEXT :limit ROWS ONLY"
            params["offset"] = offset
            params["limit"] = limit

            result = await session.execute(text(q), params)
            namespaces = [self._str_to_ns(r.namespace) for r in result.fetchall()]
            if max_depth is not None:
                namespaces = [ns[:max_depth] for ns in namespaces]
                namespaces = list(dict.fromkeys(namespaces))  # dedupe, keep order
            return namespaces

    # ─── sync stubs (raise – this is async-only) ───────────

    def batch(self, ops):
        raise NotImplementedError("Use abatch()")

    async def abatch(self, ops):
        results = []
        for op in ops:
            if isinstance(op, GetOp):
                results.append(
                    await self.aget(op.namespace, op.key, refresh_ttl=op.refresh_ttl)
                )
            elif isinstance(op, PutOp):
                await self.aput(op.namespace, op.key, op.value, index=op.index)
                results.append(None)
            elif isinstance(op, SearchOp):
                results.append(
                    await self.asearch(
                        op.namespace_prefix,
                        filter=op.filter,
                        limit=op.limit,
                        offset=op.offset,
                        query=op.query,
                        refresh_ttl=op.refresh_ttl,
                    )
                )
            elif isinstance(op, ListNamespacesOp):
                results.append(
                    await self.alist_namespaces(
                        max_depth=op.max_depth,
                        limit=op.limit,
                        offset=op.offset,
                    )
                )
            else:
                raise ValueError(f"Unknown op type: {type(op)}")
        return results

    def get(self, namespace, key, **kw):
        raise NotImplementedError("Use aget()")

    def put(self, namespace, key, value, index=None, **kw):
        raise NotImplementedError("Use aput()")

    def search(self, namespace_prefix, /, **kw):
        raise NotImplementedError("Use asearch()")

    def delete(self, namespace, key):
        raise NotImplementedError("Use adelete()")

    def list_namespaces(self, **kw):
        raise NotImplementedError("Use alist_namespaces()")

    # ─── lifecycle ──────────────────────────────────────────

    async def aclose(self) -> None:
        await self._engine.dispose()
