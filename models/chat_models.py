"""
Domain models for MenaBot chat system."Cleaned-up Pydantic models with all required fields.
"""
import enum
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field

class ChatRoleEnum(enum.Enum):
    USER = "user"
    SYSTEM = "system"
    ASSISTANT = "assistant"

class ItemType(enum.Enum):
    EVENT = "event"

class InputType(enum.Enum):
    ASK = "ask"

class ConversationType(enum.Enum):
    EVENTS = "mena_functions"

class FeedbackRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    user_id: str
    message_id: str

    rating: int
    comments: Optional[str] = None

    created_by: Optional[str] = None
    modified_by: Optional[str] = None

    function_id: Optional[int] = None
    sub_function_id: Optional[int] = None
    service_id: Optional[int] = None
    category: Optional[str] = None

class UserChatQuery(BaseModel):
    """Incoming request from client."""
    input_type: InputType
    user_input: str
    is_free_form: bool

    user_id: str
    chat_id: str | None = None
    chat_session_id: str | None = None
    config: Optional[dict] = Field(
        default_factory=lambda: {"configurable": {"thread_id": None}},
        description="Configuration options for the request",
    )
    message_id: str | None = None

    # Filters
    function: List[str] = []
    sub_function: List[str] = []
    source_url: List[str] = []
    start_date: str = ""
    end_date: str = ""
    preferred_language: Optional[str] = None

class BusinessExceptionResponse(BaseModel):
    error_code: str | None = None
    text: str | None = None

class ApplicationChatQuery(UserChatQuery):
    """Internal processing model with additional computed fields."""
    id: str = ""
    ai_content: list = []
    ai_content_free_form: str = ""
    prompt: str = ""
    source_prompt: str = ""
    summurized_prompt: str = ""
    rewritten_query: dict = {}
    error_info: BusinessExceptionResponse | None = None
    conversation_type: ConversationType = ConversationType.EVENTS

class EventchatMessage(ApplicationChatQuery):
    """A stored chat message with persistence metadata."""
    id: str = ""
    timestamp: int = 0

# Backward-compatible alias used by persistence layer imports.
ConversationChatMessage = EventchatMessage







