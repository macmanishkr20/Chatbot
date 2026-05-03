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
    # Optional. When the auth identity (``user_id``, e.g. an email)
    # differs from the EmployeeId used in the analytical tables
    # (``UserExpenses.EmployeeId`` / ``UserScoreboard.EmployeeId`` —
    # typically GPN / Workday id), the frontend can send the resolved
    # employee identifier here so the analytical agents apply RLS on
    # the correct column. When omitted, the agents fall back to
    # ``user_id``.
    employee_id: Optional[str] = None
    chat_id: str | None = None
    chat_session_id: str | None = None
    config: Optional[dict] = Field(
        default_factory=lambda: {"configurable": {"thread_id": None}},
        description="Configuration options for the request",
    )
    message_id: str | None = None
    channel_type: int = 0  # 0 or 1

    # Filters
    function: List[str] = []
    sub_function: List[str] = []
    source_url: List[str] = []
    start_date: str = ""
    end_date: str = ""
    current_date: str = ""
    preferred_language: Optional[str] = None
    content_type: str = "qna_pair"

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


# ── New request models (Claude-parity features) ──

class RegenerateRequest(BaseModel):
    """Request body for POST /chat/regenerate — re-run the last turn."""
    user_id: str
    chat_id: str
    chat_session_id: str


class RenameConversationRequest(BaseModel):
    """Request body for PATCH /conversations/{user_id}/{chat_id}/rename."""
    title: str = Field(..., max_length=200)


class CancelRequest(BaseModel):
    """Request body for POST /chat/cancel — stop an in-flight generation."""
    user_id: str
    chat_session_id: str


class ExportMessageItem(BaseModel):
    """One turn of a conversation to export."""
    role: str = Field(..., description="user or assistant")
    content: str = ""


class ExportRequest(BaseModel):
    """Request body for POST /export.

    For ``scope='message'`` populate ``content``. For ``scope='conversation'``
    populate ``messages`` (the full transcript). PPT/Keynote require
    ``template_file_id``; Word/Excel accept an optional one.
    """
    user_id: str
    format: str = Field(..., description="pptx, xlsx, docx, txt, json, pages, numbers, keynote")
    scope: str = Field(..., description="'message' or 'conversation'")
    content: Optional[str] = None
    messages: List[ExportMessageItem] = []
    template_file_id: Optional[str] = None
    title: Optional[str] = None
    preferred_language: Optional[str] = "English"


class EditMessageRequest(BaseModel):
    """Request body for POST /chat/edit — edit a message mid-thread and re-run.

    The backend walks back through checkpoint history to find the state
    just before the target message, replaces it with new_input, and
    re-runs the graph from that point. Everything after the edit point
    is discarded (branching).
    """
    user_id: str
    chat_session_id: str
    message_index: int = Field(
        ...,
        description=(
            "Zero-based index of the user message to edit within the "
            "conversation's message list. The frontend tracks this "
            "from the messages array."
        ),
    )
    new_input: str = Field(..., min_length=1, max_length=10000)
    # Carry forward the original query parameters
    is_free_form: bool = True
    function: List[str] = []
    sub_function: List[str] = []
    source_url: List[str] = []
    start_date: str = ""
    end_date: str = ""
    preferred_language: Optional[str] = None
    content_type: str = "qna_pair"







