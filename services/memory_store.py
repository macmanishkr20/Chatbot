import asyncio
from typing import Optional, Union
import aiosqlite
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from services.azure_sql_config import get_azure_sql_checkpoint_saver


async def get_azure_sql_store():
    """Get a configured AzureSQLStore instance for LangGraph cross-session memory."""
    from services.sql_store import AzureSQLStore
    from services.sql_client import SQLChatClient

    sql_config = SQLChatClient()
    store = AzureSQLStore(connection_string=sql_config.get_connection_string())
    await store.asetup()
    return store



async def get_sqlite_checkpoint_saver(db_path: str) -> AsyncSqliteSaver:
    """Get a configured SQLite checkpoint saver instance."""
    conn = await aiosqlite.connect(db_path)
    checkpointer = AsyncSqliteSaver(conn)
    await checkpointer.setup()   
    return checkpointer

def get_in_memory_checkpoint_saver() -> InMemorySaver:
    """Get an in-memory checkpoint saver instance."""
    return InMemorySaver()


async def get_persistent_memory_checkpoint_saver_async(
    type: str = "azure_sql", 
    db_path: Optional[str] = "checkpoint.db"
) -> Union[AsyncSqliteSaver, InMemorySaver]:
    """
    Get a persistent memory checkpoint saver (async version).
    Use this in async contexts like LangGraph agents.
    
    Args:
        type: Type of checkpoint saver ("sqlite", "in_memory", or "azure_sql")
        db_path: Database path (only used for SQLite)
    
    Returns:
        Configured checkpoint saver instance
    """
    if type == "sqlite":
        return await get_sqlite_checkpoint_saver(db_path)
    elif type == "in_memory":
        return get_in_memory_checkpoint_saver() 
    elif type == "azure_sql":
        # Get async Azure SQL saver and set it up
        saver = get_azure_sql_checkpoint_saver(async_mode=True)
        await saver.asetup()
        return saver
    else:
        raise ValueError(f"Unsupported checkpoint saver type: {type}")


def get_persistent_memory_checkpoint_saver_sync(type: str = "azure_sql"):
    """
    Get a persistent memory checkpoint saver (sync version).
    Only supports in_memory and azure_sql (sync mode).
    
    For async contexts (like LangGraph agents), use get_persistent_memory_checkpoint_saver_async instead.
    """
    if type == "in_memory":
        return get_in_memory_checkpoint_saver() 
    elif type == "azure_sql":
        # Get sync Azure SQL saver (already calls setup())
        return get_azure_sql_checkpoint_saver(async_mode=False)
    else:
        raise ValueError(f"Unsupported checkpoint saver type for sync: {type}. Use 'in_memory' or 'azure_sql'")