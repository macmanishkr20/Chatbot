# Global configuration instance
from services.sql_client import SQLChatClient


azure_sql_config = SQLChatClient()

def get_azure_sql_checkpoint_saver(async_mode: bool = False):
    """Get a configured Azure SQL checkpoint saver instance.
    
    Args:
        async_mode: If True, returns AsyncAzureSQLCheckpointSaver,
                   otherwise returns synchronous AzureSQLCheckpointSaver.
    
    Returns:
        AzureSQLCheckpointSaver or AsyncAzureSQLCheckpointSaver instance
    
    Note:
        For async mode, you need to call `await checkpoint_saver.asetup()`
        in an async context to initialize the database tables.
    """
    if async_mode:
        from .checkpointer import AsyncAzureSQLCheckpointSaver
        
        checkpoint_saver = AsyncAzureSQLCheckpointSaver(
            connection_string=azure_sql_config.get_connection_string(),
            table_name=azure_sql_config.checkpoint_table,
        )
        
        # Note: For async, caller must await checkpoint_saver.asetup()
        return checkpoint_saver
    else:
        from .checkpointer import AzureSQLCheckpointSaver
        
        checkpoint_saver = AzureSQLCheckpointSaver(
            connection_string=azure_sql_config.get_connection_string(),
            table_name=azure_sql_config.checkpoint_table,
        )
        
        # Automatically create tables if they don't exist
        checkpoint_saver.setup()
        
        return checkpoint_saver