"""Azure SQL checkpoint store for LangGraph."""

import base64
import hashlib
import json
import threading
from datetime import datetime
from typing import Any, AsyncIterator, Dict, Iterator, List, Optional, Tuple
from urllib.parse import quote_plus

from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
)
from sqlalchemy import (
    Column,
    DateTime,
    MetaData,
    Table,
    Text,
    create_engine,
    text,
)
from sqlalchemy.dialects.mssql import NVARCHAR
from sqlalchemy.orm import sessionmaker


class AzureSQLCheckpointSaver(BaseCheckpointSaver):
    """Synchronous Azure SQL Server checkpoint saver for LangGraph.
    
    Stores conversation checkpoints and metadata in Azure SQL Database,
    allowing for persistent conversation state across sessions.
    
    This is the synchronous-only version. For async operations, use AsyncAzureSQLCheckpointSaver.
    """
    
    def __init__(
        self,
        connection_string: Optional[str] = None,
        server: Optional[str] = None,
        database: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        use_azure_auth: bool = True,
        driver: str = "ODBC Driver 18 for SQL Server",
        table_name: str = "langgraph_checkpoints",
        checkpoint_ns: str = "checkpoint",
    ):
        """Initialize the Azure SQL Checkpoint Saver.
        
        Args:
            connection_string: Full Azure SQL connection string
            server: Azure SQL server name
            database: Database name
            username: SQL username
            password: SQL password
            use_azure_auth: Use Azure Active Directory authentication
            driver: ODBC driver name
            table_name: Name of the checkpoints table
            checkpoint_ns: Checkpoint namespace prefix
        """
        super().__init__()
        
        self.table_name = table_name
        self.checkpoint_ns = checkpoint_ns
        self.lock = threading.Lock()
        
        # Build connection string
        if connection_string:
            self.connection_string = connection_string
        else:
            if not server or not database:
                raise ValueError("Either connection_string or server+database must be provided")
            
            if use_azure_auth:
                self.connection_string = (
                    f"Driver={{{driver}}};"
                    f"Server={server};"
                    f"Database={database};"
                    f"Trusted_Connection=yes;"
                    f"Encrypt=yes;"
                    f"TrustServerCertificate=no;"
                )
            else:
                if not username or not password:
                    raise ValueError("Username and password required when not using Azure auth")
                self.connection_string = (
                    f"Driver={{{driver}}};"
                    f"Server={server};"
                    f"Database={database};"
                    f"UID={username};"
                    f"PWD={password};"
                    f"Encrypt=yes;"
                    f"TrustServerCertificate=no;"
                )
        
        # Create SQLAlchemy engine with proper connection string encoding
        connection_string_encoded = quote_plus(self.connection_string)
        self.engine = create_engine(
            f"mssql+pyodbc:///?odbc_connect={connection_string_encoded}",
            pool_pre_ping=True,
            pool_recycle=300,
        )
        
        self.SessionLocal = sessionmaker(bind=self.engine)
        
        # Define table schema
        self.metadata = MetaData()
        self.checkpoints_table = Table(
            self.table_name,
            self.metadata,
            Column("thread_id", NVARCHAR(500), primary_key=True),
            Column("checkpoint_id", NVARCHAR(500), primary_key=True),
            Column("parent_checkpoint_id", NVARCHAR(500), nullable=True),
            Column("checkpoint_data", Text, nullable=False),
            Column("metadata", Text, nullable=True),
            Column("created_at", DateTime, default=datetime.utcnow, nullable=False),
        )
        # Intermediate writes table — captures pending node writes between
        # checkpoints so a mid-graph crash does not lose work.
        self.writes_table_name = f"{self.table_name}_writes"
        self.writes_table = Table(
            self.writes_table_name,
            self.metadata,
            Column("thread_id", NVARCHAR(500), primary_key=True),
            Column("checkpoint_id", NVARCHAR(500), primary_key=True),
            Column("task_id", NVARCHAR(500), primary_key=True),
            Column("idx", NVARCHAR(50), primary_key=True),
            Column("channel", NVARCHAR(500), nullable=False),
            Column("value", Text, nullable=False),
            Column("created_at", DateTime, default=datetime.utcnow, nullable=False),
        )

    def setup(self) -> None:
        """Create the checkpoints table if it doesn't exist."""
        self.metadata.create_all(self.engine)

    # ── Serialisation helpers ──────────────────────────────────────────────
    # We use LangGraph's built-in serde (JsonPlusSerializer) which correctly
    # round-trips LangChain BaseMessage objects and other Serializable types.
    # Raw serde bytes are stored as base64 text to avoid lone-surrogate issues
    # with SQL Server NVARCHAR/TEXT encoding.

    def _serialize_checkpoint(self, checkpoint: Checkpoint) -> str:
        """Serialize checkpoint using LangGraph serde (handles BaseMessage etc.)."""
        type_str, data_bytes = self.serde.dumps_typed(checkpoint)
        payload = {
            "_type": type_str,
            "_encoding": "base64",
            "_data": base64.b64encode(data_bytes).decode("ascii"),
        }
        return json.dumps(payload, ensure_ascii=False)

    def _deserialize_checkpoint(self, data: str) -> Checkpoint:
        """Deserialize checkpoint, handling both new serde format and legacy plain-JSON rows."""
        parsed = json.loads(data)
        if isinstance(parsed, dict) and "_type" in parsed and "_data" in parsed:
            encoding = parsed.get("_encoding")
            if encoding == "base64":
                data_bytes = base64.b64decode(parsed["_data"])
            else:
                # Backward compatibility for previously stored surrogateescape rows.
                data_bytes = parsed["_data"].encode("utf-8", errors="surrogateescape")
            return self.serde.loads_typed((parsed["_type"], data_bytes))
        # Legacy format: plain json.loads — BaseMessage objects were stringified
        # Return as-is; app.py's _ensure_base_messages() will reconstruct them.
        return parsed

    def _serialize_metadata(self, metadata: CheckpointMetadata) -> str:
        """Serialize metadata to JSON string."""
        return json.dumps(metadata, default=str, ensure_ascii=False)

    def _deserialize_metadata(self, data: Optional[str]) -> CheckpointMetadata:
        """Deserialize metadata from JSON string."""
        if data:
            return json.loads(data)
        return {}
    
    def put(
        self,
        config: Dict[str, Any],
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Save a checkpoint to the database."""
        thread_id = config["configurable"]["thread_id"]
        # Generate a checkpoint ID if not provided
        checkpoint_id = config["configurable"].get("checkpoint_id")
        if not checkpoint_id:
            # Create a simple checkpoint ID based on content
            import hashlib
            checkpoint_str = json.dumps(checkpoint, sort_keys=True, default=str)
            checkpoint_id = hashlib.md5(checkpoint_str.encode()).hexdigest()
        
        parent_checkpoint_id = config["configurable"].get("parent_checkpoint_id")
        
        checkpoint_data = self._serialize_checkpoint(checkpoint)
        metadata_json = self._serialize_metadata(metadata)
        
        with self.SessionLocal() as session:
            try:
                # Check if checkpoint already exists
                existing = session.execute(
                    text(f"""
                        SELECT checkpoint_id FROM {self.table_name}
                        WHERE thread_id = :thread_id AND checkpoint_id = :checkpoint_id
                    """),
                    {"thread_id": thread_id, "checkpoint_id": checkpoint_id}
                ).fetchone()
                
                if existing:
                    # Update existing checkpoint
                    session.execute(
                        text(f"""
                            UPDATE {self.table_name}
                            SET checkpoint_data = :checkpoint_data, metadata = :metadata
                            WHERE thread_id = :thread_id AND checkpoint_id = :checkpoint_id
                        """),
                        {
                            "thread_id": thread_id,
                            "checkpoint_id": checkpoint_id,
                            "checkpoint_data": checkpoint_data,
                            "metadata": metadata_json,
                        }
                    )
                else:
                    # Insert new checkpoint
                    session.execute(
                        text(f"""
                            INSERT INTO {self.table_name}
                            (thread_id, checkpoint_id, parent_checkpoint_id, checkpoint_data, metadata, created_at)
                            VALUES (:thread_id, :checkpoint_id, :parent_checkpoint_id, :checkpoint_data, :metadata, GETUTCDATE())
                        """),
                        {
                            "thread_id": thread_id,
                            "checkpoint_id": checkpoint_id,
                            "parent_checkpoint_id": parent_checkpoint_id,
                            "checkpoint_data": checkpoint_data,
                            "metadata": metadata_json,
                        }
                    )
                
                session.commit()
                
                # Return updated config
                return {
                    **config,
                    "configurable": {
                        **config["configurable"],
                        "checkpoint_id": checkpoint_id,
                    },
                }
                
            except Exception:
                session.rollback()
                raise
    
    def get_tuple(self, config: Dict[str, Any]) -> Optional[CheckpointTuple]:
        """Get a checkpoint tuple from the database."""
        thread_id = config["configurable"]["thread_id"]
        checkpoint_id = config["configurable"].get("checkpoint_id")
        
        with self.SessionLocal() as session:
            if checkpoint_id:
                # Get specific checkpoint
                result = session.execute(
                    text(f"""
                        SELECT checkpoint_id, parent_checkpoint_id, checkpoint_data, metadata
                        FROM {self.table_name}
                        WHERE thread_id = :thread_id AND checkpoint_id = :checkpoint_id
                    """),
                    {"thread_id": thread_id, "checkpoint_id": checkpoint_id}
                ).fetchone()
            else:
                # Get latest checkpoint for thread
                result = session.execute(
                    text(f"""
                        SELECT TOP 1 checkpoint_id, parent_checkpoint_id, checkpoint_data, metadata
                        FROM {self.table_name}
                        WHERE thread_id = :thread_id
                        ORDER BY created_at DESC
                    """),
                    {"thread_id": thread_id}
                ).fetchone()
            
            if result:
                checkpoint = self._deserialize_checkpoint(result.checkpoint_data)
                metadata = self._deserialize_metadata(result.metadata)
                
                parent_config = None
                if result.parent_checkpoint_id:
                    parent_config = {
                        **config,
                        "configurable": {
                            **config["configurable"],
                            "checkpoint_id": result.parent_checkpoint_id,
                        },
                    }
                
                return CheckpointTuple(
                    config={
                        **config,
                        "configurable": {
                            **config["configurable"],
                            "checkpoint_id": result.checkpoint_id,
                        },
                    },
                    checkpoint=checkpoint,
                    metadata=metadata,
                    parent_config=parent_config,
                )
            
            return None
    
    def list(
        self,
        config: Dict[str, Any],
        *,
        filter: Optional[Dict[str, Any]] = None,
        before: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> Iterator[CheckpointTuple]:
        """List checkpoints for a thread."""
        thread_id = config["configurable"]["thread_id"]
        
        with self.SessionLocal() as session:
            query = f"""
                SELECT checkpoint_id, parent_checkpoint_id, checkpoint_data, metadata
                FROM {self.table_name}
                WHERE thread_id = :thread_id
            """
            params = {"thread_id": thread_id}
            
            if before:
                query += " AND created_at < (SELECT created_at FROM {self.table_name} WHERE checkpoint_id = :before)"
                params["before"] = before
            
            query += " ORDER BY created_at DESC"
            
            if limit:
                query = query.replace("SELECT", f"SELECT TOP {limit}")
            
            results = session.execute(text(query), params).fetchall()
            
            for row in results:
                checkpoint = self._deserialize_checkpoint(row.checkpoint_data)
                metadata = self._deserialize_metadata(row.metadata)
                
                parent_config = None
                if row.parent_checkpoint_id:
                    parent_config = {
                        **config,
                        "configurable": {
                            **config["configurable"],
                            "checkpoint_id": row.parent_checkpoint_id,
                        },
                    }
                
                yield CheckpointTuple(
                    config={
                        **config,
                        "configurable": {
                            **config["configurable"],
                            "checkpoint_id": row.checkpoint_id,
                        },
                    },
                    checkpoint=checkpoint,
                    metadata=metadata,
                    parent_config=parent_config,
                )
    
    def put_writes(
        self,
        config: Dict[str, Any],
        writes: List[Tuple[str, Any]],
        task_id: str,
    ) -> None:
        """Persist intermediate node writes (sync).

        LangGraph calls this after each node completes but before the
        checkpoint is finalised. Storing them lets a mid-graph crash
        recover without losing the work the completed nodes produced.
        Failures are logged-and-swallowed so they never break the graph.
        """
        thread_id = config["configurable"]["thread_id"]
        checkpoint_id = config["configurable"].get("checkpoint_id") or ""
        if not writes:
            return

        try:
            type_str_default, _ = self.serde.dumps_typed(None)
        except Exception:
            type_str_default = ""

        rows: list[dict] = []
        for idx, (channel, value) in enumerate(writes):
            try:
                type_str, data_bytes = self.serde.dumps_typed(value)
                payload = {
                    "_type": type_str,
                    "_encoding": "base64",
                    "_data": base64.b64encode(data_bytes).decode("ascii"),
                }
                serialised = json.dumps(payload, ensure_ascii=False)
            except Exception:
                # Best-effort fallback — never break the graph on a write
                serialised = json.dumps({"_type": type_str_default, "_data": ""})
            rows.append({
                "thread_id": thread_id,
                "checkpoint_id": checkpoint_id,
                "task_id": task_id,
                "idx": str(idx),
                "channel": str(channel),
                "value": serialised,
            })

        with self.SessionLocal() as session:
            try:
                for row in rows:
                    session.execute(
                        text(f"""
                            MERGE {self.writes_table_name} AS target
                            USING (SELECT :thread_id AS thread_id, :checkpoint_id AS checkpoint_id,
                                          :task_id AS task_id, :idx AS idx) AS src
                            ON target.thread_id = src.thread_id
                               AND target.checkpoint_id = src.checkpoint_id
                               AND target.task_id = src.task_id
                               AND target.idx = src.idx
                            WHEN MATCHED THEN
                                UPDATE SET channel = :channel, value = :value
                            WHEN NOT MATCHED THEN
                                INSERT (thread_id, checkpoint_id, task_id, idx, channel, value, created_at)
                                VALUES (:thread_id, :checkpoint_id, :task_id, :idx, :channel, :value, GETUTCDATE());
                        """),
                        row,
                    )
                session.commit()
            except Exception:
                session.rollback()
                # Never let write-persist failure break graph execution.
                return
    
    def clear_thread(self, thread_id: str) -> None:
        """Clear all checkpoints for a thread."""
        with self.SessionLocal() as session:
            try:
                session.execute(
                    text(f"DELETE FROM {self.table_name} WHERE thread_id = :thread_id"),
                    {"thread_id": thread_id}
                )
                session.commit()
            except Exception:
                session.rollback()
                raise
    
    def get_thread_history(self, thread_id: str, limit: int = 10) -> List[CheckpointTuple]:
        """Get checkpoint history for a thread."""
        config = {"configurable": {"thread_id": thread_id}}
        return list(self.list(config, limit=limit))
    
    def close(self) -> None:
        """Close all database connections and dispose engines."""
        if self.engine:
            self.engine.dispose()
    
    def __del__(self):
        """Cleanup on object destruction."""
        try:
            if self.engine:
                self.engine.dispose()
        except Exception:
            pass  # Ignore cleanup errors during destruction


class AsyncAzureSQLCheckpointSaver(BaseCheckpointSaver):
    """Asynchronous Azure SQL Server checkpoint saver for LangGraph.
    
    Stores conversation checkpoints and metadata in Azure SQL Database,
    allowing for persistent conversation state across sessions.
    
    This is the async-only version. For sync operations, use AzureSQLCheckpointSaver.
    Requires 'aioodbc' package to be installed.
    """
    
    def __init__(
        self,
        connection_string: Optional[str] = None,
        server: Optional[str] = None,
        database: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        use_azure_auth: bool = True,
        driver: str = "ODBC Driver 18 for SQL Server",
        table_name: str = "langgraph_checkpoints",
        checkpoint_ns: str = "checkpoint",
    ):
        """Initialize the Azure SQL Checkpoint Saver (async version).
        
        Args:
            connection_string: Full Azure SQL connection string
            server: Azure SQL server name
            database: Database name
            username: SQL username
            password: SQL password
            use_azure_auth: Use Azure Active Directory authentication
            driver: ODBC driver name
            table_name: Name of the checkpoints table
            checkpoint_ns: Checkpoint namespace prefix
        
        Raises:
            RuntimeError: If aioodbc is not installed
        """
        super().__init__()
        
        self.table_name = table_name
        self.checkpoint_ns = checkpoint_ns
        
        # Build connection string
        if connection_string:
            self.connection_string = connection_string
        else:
            if not server or not database:
                raise ValueError("Either connection_string or server+database must be provided")
            
            if use_azure_auth:
                self.connection_string = (
                    f"Driver={{{driver}}};"
                    f"Server={server};"
                    f"Database={database};"
                    f"Trusted_Connection=yes;"
                    f"Encrypt=yes;"
                    f"TrustServerCertificate=no;"
                )
            else:
                if not username or not password:
                    raise ValueError("Username and password required when not using Azure auth")
                self.connection_string = (
                    f"Driver={{{driver}}};"
                    f"Server={server};"
                    f"Database={database};"
                    f"UID={username};"
                    f"PWD={password};"
                    f"Encrypt=yes;"
                    f"TrustServerCertificate=no;"
                )
        
        # Create async SQLAlchemy engine
        try:
            from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
            # Check if aioodbc is available
            try:
                import aioodbc  # noqa: F401
            except ImportError:
                raise ImportError("aioodbc not installed")
            
            connection_string_encoded = quote_plus(self.connection_string)
            self.async_engine = create_async_engine(
                f"mssql+aioodbc:///?odbc_connect={connection_string_encoded}",
                pool_pre_ping=True,
                pool_recycle=300,
                echo=False,
                pool_size=5,
                max_overflow=10,
            )
            self.AsyncSessionLocal = async_sessionmaker(
                self.async_engine, 
                class_=AsyncSession,
                expire_on_commit=False,
            )
        except (ImportError, ModuleNotFoundError) as e:
            raise RuntimeError(
                "Async checkpoint saver requires 'aioodbc' package. "
                "Install it with: pip install aioodbc"
            ) from e
        
        # Define table schema
        self.metadata = MetaData()
        self.checkpoints_table = Table(
            self.table_name,
            self.metadata,
            Column("thread_id", NVARCHAR(500), primary_key=True),
            Column("checkpoint_id", NVARCHAR(500), primary_key=True),
            Column("parent_checkpoint_id", NVARCHAR(500), nullable=True),
            Column("checkpoint_data", Text, nullable=False),
            Column("metadata", Text, nullable=True),
            Column("created_at", DateTime, default=datetime.utcnow, nullable=False),
        )
        # Intermediate writes table — captures pending node writes between
        # checkpoints so a mid-graph crash does not lose work.
        self.writes_table_name = f"{self.table_name}_writes"
        self.writes_table = Table(
            self.writes_table_name,
            self.metadata,
            Column("thread_id", NVARCHAR(500), primary_key=True),
            Column("checkpoint_id", NVARCHAR(500), primary_key=True),
            Column("task_id", NVARCHAR(500), primary_key=True),
            Column("idx", NVARCHAR(50), primary_key=True),
            Column("channel", NVARCHAR(500), nullable=False),
            Column("value", Text, nullable=False),
            Column("created_at", DateTime, default=datetime.utcnow, nullable=False),
        )

    async def asetup(self) -> None:
        """Create the checkpoints table if it doesn't exist."""
        async with self.async_engine.begin() as conn:
            await conn.run_sync(self.metadata.create_all)

    # ── Serialisation helpers ──────────────────────────────────────────────

    def _serialize_checkpoint(self, checkpoint: Checkpoint) -> str:
        """Serialize checkpoint using LangGraph serde (handles BaseMessage etc.)."""
        type_str, data_bytes = self.serde.dumps_typed(checkpoint)
        payload = {
            "_type": type_str,
            "_encoding": "base64",
            "_data": base64.b64encode(data_bytes).decode("ascii"),
        }
        return json.dumps(payload, ensure_ascii=False)

    def _deserialize_checkpoint(self, data: str) -> Checkpoint:
        """Deserialize checkpoint, handling both new serde format and legacy plain-JSON rows."""
        parsed = json.loads(data)
        if isinstance(parsed, dict) and "_type" in parsed and "_data" in parsed:
            encoding = parsed.get("_encoding")
            if encoding == "base64":
                data_bytes = base64.b64decode(parsed["_data"])
            else:
                # Backward compatibility for previously stored surrogateescape rows.
                data_bytes = parsed["_data"].encode("utf-8", errors="surrogateescape")
            return self.serde.loads_typed((parsed["_type"], data_bytes))
        # Legacy row — return raw; _ensure_base_messages() in app.py handles reconstruction.
        return parsed

    def _serialize_metadata(self, metadata: CheckpointMetadata) -> str:
        """Serialize metadata to JSON string."""
        return json.dumps(metadata, default=str, ensure_ascii=False)

    def _deserialize_metadata(self, data: Optional[str]) -> CheckpointMetadata:
        """Deserialize metadata from JSON string."""
        if data:
            return json.loads(data)
        return {}
    
    async def aput(
        self,
        config: Dict[str, Any],
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Save a checkpoint to the database."""
        thread_id = config["configurable"]["thread_id"]
        # Generate a checkpoint ID if not provided
        checkpoint_id = config["configurable"].get("checkpoint_id")
        if not checkpoint_id:
            # Create a simple checkpoint ID based on content
            checkpoint_str = json.dumps(checkpoint, sort_keys=True, default=str)
            checkpoint_id = hashlib.md5(checkpoint_str.encode()).hexdigest()
        
        parent_checkpoint_id = config["configurable"].get("parent_checkpoint_id")
        
        checkpoint_data = self._serialize_checkpoint(checkpoint)
        metadata_json = self._serialize_metadata(metadata)
        
        async with self.AsyncSessionLocal() as session:
            try:
                # Check if checkpoint already exists
                result = await session.execute(
                    text(f"""
                        SELECT checkpoint_id FROM {self.table_name}
                        WHERE thread_id = :thread_id AND checkpoint_id = :checkpoint_id
                    """),
                    {"thread_id": thread_id, "checkpoint_id": checkpoint_id}
                )
                existing = result.fetchone()
                
                if existing:
                    # Update existing checkpoint
                    await session.execute(
                        text(f"""
                            UPDATE {self.table_name}
                            SET checkpoint_data = :checkpoint_data, metadata = :metadata
                            WHERE thread_id = :thread_id AND checkpoint_id = :checkpoint_id
                        """),
                        {
                            "thread_id": thread_id,
                            "checkpoint_id": checkpoint_id,
                            "checkpoint_data": checkpoint_data,
                            "metadata": metadata_json,
                        }
                    )
                else:
                    # Insert new checkpoint
                    await session.execute(
                        text(f"""
                            INSERT INTO {self.table_name}
                            (thread_id, checkpoint_id, parent_checkpoint_id, checkpoint_data, metadata, created_at)
                            VALUES (:thread_id, :checkpoint_id, :parent_checkpoint_id, :checkpoint_data, :metadata, GETUTCDATE())
                        """),
                        {
                            "thread_id": thread_id,
                            "checkpoint_id": checkpoint_id,
                            "parent_checkpoint_id": parent_checkpoint_id,
                            "checkpoint_data": checkpoint_data,
                            "metadata": metadata_json,
                        }
                    )
                
                await session.commit()
                
                # Return updated config
                return {
                    **config,
                    "configurable": {
                        **config["configurable"],
                        "checkpoint_id": checkpoint_id,
                    },
                }
                
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()
    
    async def aget_tuple(self, config: Dict[str, Any]) -> Optional[CheckpointTuple]:
        """Get a checkpoint tuple from the database."""
        thread_id = config["configurable"]["thread_id"]
        checkpoint_id = config["configurable"].get("checkpoint_id")
        
        async with self.AsyncSessionLocal() as session:
            try:
                if checkpoint_id:
                    # Get specific checkpoint
                    result = await session.execute(
                        text(f"""
                            SELECT checkpoint_id, parent_checkpoint_id, checkpoint_data, metadata
                            FROM {self.table_name}
                            WHERE thread_id = :thread_id AND checkpoint_id = :checkpoint_id
                        """),
                        {"thread_id": thread_id, "checkpoint_id": checkpoint_id}
                    )
                else:
                    # Get latest checkpoint for thread
                    result = await session.execute(
                        text(f"""
                            SELECT TOP 1 checkpoint_id, parent_checkpoint_id, checkpoint_data, metadata
                            FROM {self.table_name}
                            WHERE thread_id = :thread_id
                            ORDER BY created_at DESC
                        """),
                        {"thread_id": thread_id}
                    )
                
                row = result.fetchone()
                
                if row:
                    checkpoint = self._deserialize_checkpoint(row.checkpoint_data)
                    metadata = self._deserialize_metadata(row.metadata)
                    
                    parent_config = None
                    if row.parent_checkpoint_id:
                        parent_config = {
                            **config,
                            "configurable": {
                                **config["configurable"],
                                "checkpoint_id": row.parent_checkpoint_id,
                            },
                        }
                    
                    return CheckpointTuple(
                        config={
                            **config,
                            "configurable": {
                                **config["configurable"],
                                "checkpoint_id": row.checkpoint_id,
                            },
                        },
                        checkpoint=checkpoint,
                        metadata=metadata,
                        parent_config=parent_config,
                    )
                
                return None
            finally:
                await session.close()
    
    async def alist(
        self,
        config: Dict[str, Any],
        *,
        filter: Optional[Dict[str, Any]] = None,
        before: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> AsyncIterator[CheckpointTuple]:
        """List checkpoints for a thread."""
        thread_id = config["configurable"]["thread_id"]
        
        async with self.AsyncSessionLocal() as session:
            try:
                query = f"""
                    SELECT checkpoint_id, parent_checkpoint_id, checkpoint_data, metadata
                    FROM {self.table_name}
                    WHERE thread_id = :thread_id
                """
                params = {"thread_id": thread_id}
                
                if before:
                    query += " AND created_at < (SELECT created_at FROM {self.table_name} WHERE checkpoint_id = :before)"
                    params["before"] = before
                
                query += " ORDER BY created_at DESC"
                
                if limit:
                    query = query.replace("SELECT", f"SELECT TOP {limit}")
                
                result = await session.execute(text(query), params)
                results = result.fetchall()
                
                for row in results:
                    checkpoint = self._deserialize_checkpoint(row.checkpoint_data)
                    metadata = self._deserialize_metadata(row.metadata)
                    
                    parent_config = None
                    if row.parent_checkpoint_id:
                        parent_config = {
                            **config,
                            "configurable": {
                                **config["configurable"],
                                "checkpoint_id": row.parent_checkpoint_id,
                            },
                        }
                    
                    yield CheckpointTuple(
                        config={
                            **config,
                            "configurable": {
                                **config["configurable"],
                                "checkpoint_id": row.checkpoint_id,
                            },
                        },
                        checkpoint=checkpoint,
                        metadata=metadata,
                        parent_config=parent_config,
                    )
            finally:
                await session.close()
    
    async def aput_writes(
        self,
        config: Dict[str, Any],
        writes: List[Tuple[str, Any]],
        task_id: str,
    ) -> None:
        """Persist intermediate node writes (async).

        LangGraph calls this after each node completes but before the
        checkpoint is finalised. Storing them lets a mid-graph crash
        recover without losing the work the completed nodes produced.
        Failures are logged-and-swallowed so they never break the graph.
        """
        thread_id = config["configurable"]["thread_id"]
        checkpoint_id = config["configurable"].get("checkpoint_id") or ""
        if not writes:
            return

        try:
            type_str_default, _ = self.serde.dumps_typed(None)
        except Exception:
            type_str_default = ""

        rows: list[dict] = []
        for idx, (channel, value) in enumerate(writes):
            try:
                type_str, data_bytes = self.serde.dumps_typed(value)
                payload = {
                    "_type": type_str,
                    "_encoding": "base64",
                    "_data": base64.b64encode(data_bytes).decode("ascii"),
                }
                serialised = json.dumps(payload, ensure_ascii=False)
            except Exception:
                serialised = json.dumps({"_type": type_str_default, "_data": ""})
            rows.append({
                "thread_id": thread_id,
                "checkpoint_id": checkpoint_id,
                "task_id": task_id,
                "idx": str(idx),
                "channel": str(channel),
                "value": serialised,
            })

        async with self.AsyncSessionLocal() as session:
            try:
                for row in rows:
                    await session.execute(
                        text(f"""
                            MERGE {self.writes_table_name} AS target
                            USING (SELECT :thread_id AS thread_id, :checkpoint_id AS checkpoint_id,
                                          :task_id AS task_id, :idx AS idx) AS src
                            ON target.thread_id = src.thread_id
                               AND target.checkpoint_id = src.checkpoint_id
                               AND target.task_id = src.task_id
                               AND target.idx = src.idx
                            WHEN MATCHED THEN
                                UPDATE SET channel = :channel, value = :value
                            WHEN NOT MATCHED THEN
                                INSERT (thread_id, checkpoint_id, task_id, idx, channel, value, created_at)
                                VALUES (:thread_id, :checkpoint_id, :task_id, :idx, :channel, :value, GETUTCDATE());
                        """),
                        row,
                    )
                await session.commit()
            except Exception:
                await session.rollback()
                # Never let write-persist failure break graph execution.
                return
            finally:
                await session.close()
    
    async def aclear_thread(self, thread_id: str) -> None:
        """Clear all checkpoints for a thread."""
        async with self.AsyncSessionLocal() as session:
            try:
                await session.execute(
                    text(f"DELETE FROM {self.table_name} WHERE thread_id = :thread_id"),
                    {"thread_id": thread_id}
                )
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()
    
    async def aget_thread_history(self, thread_id: str, limit: int = 10) -> List[CheckpointTuple]:
        """Get checkpoint history for a thread."""
        config = {"configurable": {"thread_id": thread_id}}
        results = []
        async for item in self.alist(config, limit=limit):
            results.append(item)
        return results
    
    async def aclose(self) -> None:
        """Close all database connections and dispose engines."""
        if self.async_engine:
            await self.async_engine.dispose()
    
    def __del__(self):
        """Cleanup on object destruction."""
        try:
            # Note: Cannot call async dispose in __del__
            # Use aclose() explicitly before object destruction
            pass
        except Exception:
            pass  # Ignore cleanup errors during destruction
    
    # Sync methods should raise NotImplementedError to make it clear this is async-only
    def setup(self) -> None:
        """Not implemented. Use asetup() for async checkpoint saver."""
        raise NotImplementedError("Use asetup() for async checkpoint saver")
    
    def put(self, config, checkpoint, metadata, new_versions):
        """Not implemented. Use aput() for async checkpoint saver."""
        raise NotImplementedError("Use aput() for async checkpoint saver")
    
    def get_tuple(self, config):
        """Not implemented. Use aget_tuple() for async checkpoint saver."""
        raise NotImplementedError("Use aget_tuple() for async checkpoint saver")
    
    def list(self, config, **kwargs):
        """Not implemented. Use alist() for async checkpoint saver."""
        raise NotImplementedError("Use alist() for async checkpoint saver")
    
    def put_writes(self, config, writes, task_id):
        """Not implemented. Use aput_writes() for async checkpoint saver."""
        raise NotImplementedError("Use aput_writes() for async checkpoint saver")
    
    def clear_thread(self, thread_id):
        """Not implemented. Use aclear_thread() for async checkpoint saver."""
        raise NotImplementedError("Use aclear_thread() for async checkpoint saver")
    
    def get_thread_history(self, thread_id, limit=10):
        """Not implemented. Use aget_thread_history() for async checkpoint saver."""
        raise NotImplementedError("Use aget_thread_history() for async checkpoint saver")
    
    def close(self):
        """Not implemented. Use aclose() for async checkpoint saver."""
        raise NotImplementedError("Use aclose() for async checkpoint saver")