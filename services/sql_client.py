"""
SQL Server persistence layer for conversations and messages.
Ported from infrastructure/repositories/chats.py + sqldb_service.py.
"""
import asyncio
import json
from datetime import datetime, timezone
from typing import List, Tuple
import uuid

import pyodbc

from config import AZURE_SQL_CHECKPOINT_TABLE, MSSQL_CONNECTION_STRING
from models.chat_models import (
    ApplicationChatQuery,
    ConversationType,
    ConversationChatMessage,
    InputType,
    FeedbackRequest,
)

USER_ACTOR = 0
BOT_ACTOR = 1


class SQLChatClient:
    """Singleton SQL chat persistence client."""

    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        self.connection_string = MSSQL_CONNECTION_STRING
        self.checkpoint_table = AZURE_SQL_CHECKPOINT_TABLE

    def get_connection_string(self) -> str:
        """Get the Azure SQL connection string."""
        if self.connection_string:
            return self.connection_string
        
        if not self.server or not self.database:
            raise ValueError("Azure SQL server and database must be configured")
        
        if self.use_azure_auth:
            return (
                f"Driver={{{self.driver}}};"
                f"Server={self.server};"
                f"Database={self.database};"
                f"Trusted_Connection=yes;"
                f"Encrypt=yes;"
                f"TrustServerCertificate=no;"
            )
        else:
            if not self.username or not self.password:
                raise ValueError("Username and password required when not using Azure auth")
            return (
                f"Driver={{{self.driver}}};"
                f"Server={self.server};"
                f"Database={self.database};"
                f"UID={self.username};"
                f"PWD={self.password};"
                f"Encrypt=yes;"
                f"TrustServerCertificate=no;"
            )

    def _get_connection(self) -> pyodbc.Connection:
        return pyodbc.connect(self.connection_string)

    def _check_connection(self):
        conn = self._get_connection()
        conn.close()

    async def connect(self):
        await asyncio.to_thread(self._check_connection)

    async def ensure(self):
        def _run():
            conn = self._get_connection()
            cursor = conn.cursor()
            try:
                cursor.execute(
                    """
                    IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='Conversations' AND xtype='U')
                    CREATE TABLE Conversations (
                        Id               INT IDENTITY(1,1) PRIMARY KEY,
                        UserId           NVARCHAR(256) NOT NULL,
                        Title            NVARCHAR(1000) NULL,
                        ChannelType      INT NOT NULL DEFAULT 0,
                        ConversationType NVARCHAR(50) NULL,
                        IsActive         BIT NOT NULL DEFAULT 1,
                        IsDeleted        BIT NOT NULL DEFAULT 0,
                        CreatedAt        DATETIME2 NOT NULL,
                        CreatedBy        NVARCHAR(256) NULL,
                        ModifiedAt       DATETIME2 NOT NULL,
                        ModifiedBy       NVARCHAR(256) NULL
                    )
                    """
                )
                cursor.execute(
                    """
                    IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='ChatMessages' AND xtype='U')
                    CREATE TABLE ChatMessages (
                        Id               INT IDENTITY(1,1) PRIMARY KEY,
                        ConversationSessionId   INT NOT NULL,
                        MessageId        NVARCHAR(256) NULL,
                        UserId           NVARCHAR(256) NULL,
                        UserPrompt          NVARCHAR(MAX) NULL,
                        SourcePrompt        NVARCHAR(MAX) NULL,
                        ConversationType NVARCHAR(50) NULL,
                        AiContentFreeForm NVARCHAR(MAX) NULL,
                        SummarizedContent NVARCHAR(MAX) NULL,
                        IsActive         BIT NOT NULL DEFAULT 1,
                        IsDeleted        BIT NOT NULL DEFAULT 0,
                        CreatedAt        DATETIME2 NOT NULL,
                        CreatedBy        NVARCHAR(256) NULL,
                        ModifiedAt       DATETIME2 NOT NULL,
                        ModifiedBy       NVARCHAR(256) NULL
                    )
                    """
                )
                
                cursor.execute(
                    """
                    IF COL_LENGTH('ChatMessages', 'SourcePrompt') IS NULL
                        ALTER TABLE ChatMessages ADD SourcePrompt NVARCHAR(MAX) NULL
                    """
                )

                conn.commit()
            finally:
                cursor.close()
                conn.close()

        await asyncio.to_thread(_run)

    # ───────────────── Conversation CRUD ─────────────────

    async def create_conversation(self, query: ApplicationChatQuery) -> dict:
        def _run():
            conn = self._get_connection()
            cursor = conn.cursor()
            now = datetime.utcnow()
            try:
                cursor.execute(
                    """
                    INSERT INTO Conversations
                        (UserId, Title, ChannelType, ConversationType,
                         IsActive, IsDeleted, CreatedAt, CreatedBy, ModifiedAt, ModifiedBy)
                    OUTPUT INSERTED.*
                    VALUES (?, ?, ?, ?, 1, 0, ?, ?, ?, ?)
                    """,
                    query.user_id,
                    query.user_input,
                    0,
                    str(query.conversation_type.value),  #it should be like "lms", "claims"
                    now,
                    query.user_id,
                    now,
                    query.user_id,
                )
                columns = [col[0] for col in cursor.description]
                row = cursor.fetchone()
                conn.commit()
                return dict(zip(columns, row)) if row else None
            finally:
                cursor.close()
                conn.close()

        return await asyncio.to_thread(_run)

    async def upsert_chat(self, chat: dict) -> dict:
        def _run():
            conn = self._get_connection()
            cursor = conn.cursor()
            now = datetime.utcnow()
            try:
                cursor.execute(
                    """
                    UPDATE Conversations
                    SET Title = ?, ModifiedAt = ?, ModifiedBy = ?
                    WHERE Id = ?
                    """,
                    chat.get("title") or chat.get("Title"),
                    now,
                    chat.get("userId") or chat.get("UserId"),
                    chat.get("id") or chat.get("Id"),
                )
                conn.commit()
                return chat
            finally:
                cursor.close()
                conn.close()

        return await asyncio.to_thread(_run)

    async def get_or_create_chat(self, query: ApplicationChatQuery) -> Tuple[bool, dict]:
        created = False
        if query.chat_id:
            def _run():
                conn = self._get_connection()
                cursor = conn.cursor()
                try:
                    #print(f"[DEBUG]----{query.chat_id}, {query.user_id}")
                    cursor.execute(
                        "SELECT * FROM Conversations WHERE Id = ? AND UserId = ? AND IsDeleted = 0",
                        query.chat_id,
                        query.user_id,
                    )
                    columns = [col[0] for col in cursor.description]
                    row = cursor.fetchone()
                    return dict(zip(columns, row)) if row else None
                finally:
                    cursor.close()
                    conn.close()

            conversation = await asyncio.to_thread(_run)
            if not conversation:
                raise ValueError("Conversation not found")
            return created, conversation
        else:
            conversation = await self.create_conversation(query)
            return True, conversation

    # ───────────────── Message CRUD ─────────────────

    async def message_create(self, query: ApplicationChatQuery) -> ConversationChatMessage:
        created_chat, chat = await self.get_or_create_chat(query)
        if not created_chat:
            await self.upsert_chat(chat)

        def _run():
            conn = self._get_connection()
            cursor = conn.cursor()
            now = datetime.utcnow()
            message_id = str(uuid.uuid4())
            try:
                cursor.execute(
                    """

                    INSERT INTO ChatMessages
                        (ConversationSessionId, MessageId, UserId, UserPrompt, SourcePrompt, ConversationType, AiContentFreeForm, SummarizedContent,
                         IsActive, IsDeleted, CreatedAt, CreatedBy, ModifiedAt, ModifiedBy)
                    OUTPUT INSERTED.*
                    VALUES (?, ?, ?, ?, NULL, ?, NULL, NULL, 1, 0, ?, ?, ?, ?)
                    """,
                    chat["Id"],
                    message_id,
                    query.user_id,
                    query.user_input,
                    str(query.conversation_type.value),  #it should be like "lms", "claims"
                    now,
                    query.user_id,
                    now,
                    query.user_id,
                )
                columns = [col[0] for col in cursor.description]
                row = cursor.fetchone()
                conn.commit()
                return dict(zip(columns, row)) if row else None
            finally:
                cursor.close()
                conn.close()

        row = await asyncio.to_thread(_run)
        return ConversationChatMessage(**_row_to_message_dict(row, query)) if row else None

    async def message_list(self, query: ApplicationChatQuery) -> List[ConversationChatMessage]:
        if query.input_type == InputType.ASK and not query.chat_id:
            return []

        def _run():
            conn = self._get_connection()
            cursor = conn.cursor()
            conv_type = str(query.conversation_type.value)
            try:
                if query.input_type == InputType.ASK:
                    cursor.execute(
                        """
                        SELECT * FROM ChatMessages
                        WHERE ConversationSessionId = ? AND ConversationType = ? AND IsDeleted = 0
                        ORDER BY CreatedAt DESC
                        """,
                        query.chat_id,
                        conv_type,
                    )
                
                else:
                    raise NotImplementedError(f"Input type {query.input_type} not implemented")

                columns = [col[0] for col in cursor.description]
                return [dict(zip(columns, r)) for r in cursor.fetchall()]
            finally:
                cursor.close()
                conn.close()

        rows = await asyncio.to_thread(_run)
        return [ConversationChatMessage(**_row_to_message_dict(r, query)) for r in rows]

    async def message_list_update(
        self, query: ApplicationChatQuery, history: List[ConversationChatMessage]
    ) -> Tuple[ConversationChatMessage, List[ConversationChatMessage]]:
        ####
        # if query.message_id and query.input_type in (InputType.EDIT, InputType.REGENERATE):
        #     def _delete():
        #         conn = self._get_connection()
        #         cursor = conn.cursor()
        #         try:
        #             cursor.execute(
        #                 """
        #                 UPDATE ChatMessages
        #                 SET IsDeleted = 1
        #                 WHERE ConversationSessionId = ? AND IsDeleted = 0
        #                   AND CreatedAt >= (
        #                       SELECT CreatedAt FROM ChatMessages WHERE Id = ? AND IsDeleted = 0
        #                   )
        #                 """,
        #                 query.chat_id,
        #                 query.message_id,
        #             )
        #             conn.commit()
        #         finally:
        #             cursor.close()
        #             conn.close()

        #     await asyncio.to_thread(_delete)


        new_msg = await self.message_create(query)
        return new_msg, [new_msg] + history
    
    async def message_list_empty_response(self, query: ApplicationChatQuery) -> List[ConversationChatMessage]:
        empty_message = ConversationChatMessage(**query.dict())
        empty_message.timestamp = int(datetime.now(tz=timezone.utc).timestamp())
        empty_message.id = str(uuid.uuid4())
        return [empty_message]

    async def save_ai_content(self, app_query: ApplicationChatQuery):
        def _run():
            conn = self._get_connection()
            cursor = conn.cursor()
            try:
                cursor.execute(
                    """
                    UPDATE ChatMessages
                    SET SummarizedContent =
                            CASE
                                WHEN NULLIF(SummarizedContent, '') IS NULL THEN ?
                                ELSE CONCAT(SummarizedContent, CHAR(10), ?)
                            END,
                        SourcePrompt = ?
                    WHERE Id = ?
                    """,
                    app_query.summurized_prompt,
                    app_query.summurized_prompt,
                    app_query.prompt or app_query.user_input,
                    app_query.id,
                )
                conn.commit()
            except Exception as e:
                print(f"Error saving AI content: {e}")
            finally:
                cursor.close()
                conn.close()

        await asyncio.to_thread(_run)

    async def save_ai_content_free_form(self, app_query: ApplicationChatQuery):
        def _run():
            conn = self._get_connection()
            cursor = conn.cursor()
            try:
                cursor.execute(
                    """
                    UPDATE ChatMessages
                    SET AiContentFreeForm = ?,
                        SourcePrompt     = ?
                    WHERE Id = ?
                    """,
                    json.dumps(app_query.ai_content_free_form),
                    app_query.prompt or app_query.user_input,
                    app_query.id,
                )
                conn.commit()
            except Exception as e:
                print(f"Error saving free-form content: {e}")
            finally:
                cursor.close()
                conn.close()

        await asyncio.to_thread(_run)

    # ───────────────── Simple insert (for /conversations/ingest) ─────────────

    async def get_conversations_by_user(self, user_id: str) -> list[dict]:
        """Return all active conversations for a given user, newest first."""
        def _run():
            conn = self._get_connection()
            cursor = conn.cursor()
            try:
                cursor.execute(
                    """
                    SELECT Id, UserId, Title, ConversationType, CreatedAt, ModifiedAt
                    FROM Conversations
                    WHERE UserId = ? AND IsDeleted = 0
                    ORDER BY ModifiedAt DESC
                    """,
                    user_id,
                )
                columns = [col[0] for col in cursor.description]
                return [dict(zip(columns, r)) for r in cursor.fetchall()]
            finally:
                cursor.close()
                conn.close()

        return await asyncio.to_thread(_run)

    async def get_messages_by_conversation(self, conversation_id: int, user_id: str) -> list[dict]:
        """Return all messages for a conversation, oldest first."""
        def _run():
            conn = self._get_connection()
            cursor = conn.cursor()
            try:
                cursor.execute(
                    """
                    SELECT cm.Id, cm.ConversationSessionId, cm.MessageId, cm.UserId,
                           cm.UserPrompt, cm.SourcePrompt, cm.AiContentFreeForm,
                           cm.SummarizedContent, cm.CreatedAt
                    FROM ChatMessages cm
                    INNER JOIN Conversations c ON c.Id = cm.ConversationSessionId
                    WHERE cm.ConversationSessionId = ? AND c.UserId = ?
                      AND cm.IsDeleted = 0 AND c.IsDeleted = 0
                    ORDER BY cm.CreatedAt ASC
                    """,
                    conversation_id,
                    user_id,
                )
                columns = [col[0] for col in cursor.description]
                return [dict(zip(columns, r)) for r in cursor.fetchall()]
            finally:
                cursor.close()
                conn.close()

        return await asyncio.to_thread(_run)

    async def save_feedback(self, payload: FeedbackRequest):
        def _run():
            conn = self._get_connection()
            cursor = conn.cursor()
            now = datetime.now(timezone.utc)
            try:
                cursor.execute(
                    """
                    IF NOT EXISTS (
                        SELECT * FROM sysobjects WHERE name='MessageFeedback' AND xtype='U'
                    )
                    CREATE TABLE dbo.MessageFeedback (
                        Id            INT IDENTITY(1,1) PRIMARY KEY,
                        UserId        NVARCHAR(256) NOT NULL,
                        MessageId     NVARCHAR(256) NOT NULL,
                        Rating        INT NOT NULL,
                        Comments      NVARCHAR(MAX) NULL,
                        IsActive      BIT NOT NULL,
                        IsDeleted     BIT NOT NULL,
                        CreatedAt     DATETIMEOFFSET NULL,
                        CreatedBy     NVARCHAR(255) NULL,
                        ModifiedAt    DATETIMEOFFSET NULL,
                        ModifiedBy    NVARCHAR(255) NULL,
                        FunctionId    INT NULL,
                        SubFunctionId INT NULL,
                        ServiceId     INT NULL,
                        Category      NVARCHAR(255) NULL
                    )
                    """
                )

                cursor.execute(
                    """
                    INSERT INTO dbo.MessageFeedback
                    (UserId, MessageId, Rating, Comments, IsActive, IsDeleted,
                     CreatedAt, CreatedBy, ModifiedAt, ModifiedBy,
                     FunctionId, SubFunctionId, ServiceId, Category)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    payload.user_id,
                    payload.message_id,
                    payload.rating,
                    payload.comments,
                    True,
                    False,
                    now,
                    payload.created_by,
                    now,
                    payload.modified_by,
                    payload.function_id,
                    payload.sub_function_id,
                    payload.service_id,
                    payload.category,
                )
                conn.commit()
            finally:
                cursor.close()
                conn.close()

        await asyncio.to_thread(_run)

def _row_to_message_dict(row: dict, query=None) -> dict:
    """Map a SQL row to the fields expected by EventChatMessage."""
    return {
        "id": str(row.get("Id") or ""),
        "chat_id": str(row.get("ConversationSessionId", "")),
        "user_id": row.get("UserId") or (query.user_id if query else ""),
        "user_input": row.get("UserPrompt") or "",
        "input_type": (query.input_type if query else InputType.ASK),
        "is_free_form": (query.is_free_form if query else False),
        "conversation_type": row.get("ConversationType") or "events",
        "timestamp": int(row["CreatedAt"].timestamp()) if row.get("CreatedAt") else 0,
        "user_prompt": row.get("UserPrompt") or "",
        "source_prompt": row.get("SourcePrompt") or "",
        "ai_content_free_form": row.get("AiContentFreeForm") or "",
        "message_id": row.get("MessageId") or "",
}


def _map_event_to_db(event) -> dict:
    if isinstance(event, dict):
        return event
    return {
        "id": event.id,
        "eventType": event.eventType,
        "event_": event.event_,
        "eventTitle": event.eventTitle,
        "sectors": event.sectors,
        "firstAppear": event.firstAppear,
        "lastAppear": event.lastAppear,
        "membersVolume": event.membersVolume,
        "membersfirstApperList": event.membersfirstApperList,
        "newsSourceList": event.newsSourceList,
        "secondaryTriggers": event.secondaryTriggers,
        "alertId": event.alertId,
        "datasource": event.datasource,
        "score": event.score,
        "event_state": event.event_state.value if hasattr(event.event_state, "value") else event.event_state,
        "sub_function": event.sub_function,
        "source_url": event.source_url,
    }



























