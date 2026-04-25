/** SSE event types received from the /chat endpoint. */
export interface ThoughtEvent {
  type: 'thought';
  node: string;
  message: string;
}

export interface ContentEvent {
  type: 'content';
  node: string;
  content: string;
}

export interface FinalEvent {
  type: 'final';
  chat_id: string | number | null;
  message_id: string | null;
  ai_content: unknown;
  suggestive_actions?: SuggestiveAction[];
  conversation_title?: string | null;
  cancelled?: boolean;
  template_request?: TemplateRequest | null;
  download?: DownloadInfo | null;
}

/** Backend asks the user to upload a template before generating a document. */
export interface TemplateRequest {
  format: string;       // canonical key: pptx | keynote | xlsx | …
  extension: string;    // file extension expected for the upload
  topic: string;        // original user request, replayed after upload
}

/** Generated-document download payload. */
export interface DownloadInfo {
  file_id: string;
  filename: string;
  extension: string;
  format: string;
  url: string;          // path-only — append to API base
  ios_note?: string | null;
}

export interface UploadTemplateResponse {
  template_file_id: string;
  extension: string;
  filename: string;
  size: number;
}

export type SSEEvent = ThoughtEvent | ContentEvent | FinalEvent;

/** Suggestive action button from the Supervisor. */
export interface SuggestiveAction {
  short_title: string;
  description?: string;
}

/** Parsed citation entry. */
export interface Citation {
  indexes: number[];
  /** URL or document/source name. */
  source: string;
  /** Whether the source is a clickable URL. */
  isUrl: boolean;
}

/** Chain-of-thought step displayed in the thinking panel. */
export interface ThinkingStep {
  node: string;
  message: string;
  state: 'pending' | 'running' | 'done';
}

/** A single message in the chat window. */
export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  /** Index of this user message (0-based, only for role=user). */
  userMessageIndex?: number;
  thinkingSteps?: ThinkingStep[];
  thinkingCollapsed?: boolean;
  suggestiveActions?: SuggestiveAction[];
  chatId?: string | number | null;
  messageId?: string | null;
  conversationTitle?: string | null;
  timestamp?: Date;
  isStreaming?: boolean;
  isEditing?: boolean;
  editText?: string;
  citations?: Citation[];
  /** Set when the assistant is asking the user to upload a template. */
  templateRequest?: TemplateRequest | null;
  /** Set when the assistant has produced a downloadable document. */
  download?: DownloadInfo | null;
}

/** Conversation session from /conversations endpoint. */
export interface Conversation {
  Id: number;
  UserId: string;
  Title: string;
  /** Original LangGraph chat_session_id — used to restore thread for edit/regenerate. */
  ChatSessionId?: string | null;
  ConversationType: string;
  CreatedAt: string;
  ModifiedAt: string;
}

/** Stored message from /conversations/{user_id}/{chat_id}/messages. */
export interface StoredMessage {
  Id: number;
  ConversationSessionId: number;
  MessageId: string;
  UserId: string;
  UserPrompt: string;
  SourcePrompt: string;
  AiContentFreeForm: string;
  SummarizedContent: string;
  CreatedAt: string;
}

/** Request body for POST /chat. */
export interface ChatRequest {
  input_type: 'ask';
  user_input: string;
  is_free_form: boolean;
  user_id: string;
  chat_id?: string | null;
  chat_session_id?: string | null;
  function: string[];
  sub_function: string[];
  source_url: string[];
  start_date: string;
  end_date: string;
  preferred_language?: string;
  /** Document export — populated after the user uploads a template. */
  export_format?: string;
  template_file_id?: string;
}

/** Request body for POST /chat/edit. */
export interface EditRequest {
  user_id: string;
  chat_session_id: string;
  message_index: number;
  new_input: string;
  is_free_form: boolean;
  function: string[];
  sub_function: string[];
  source_url: string[];
  start_date: string;
  end_date: string;
}

/** Request body for POST /chat/regenerate. */
export interface RegenerateRequest {
  user_id: string;
  chat_id: string;
  chat_session_id: string;
}

/** Request body for POST /chat/cancel. */
export interface CancelRequest {
  user_id: string;
  chat_session_id: string;
}

/** Request body for PATCH rename. */
export interface RenameRequest {
  title: string;
}

/** Request body for POST /feedback. */
export interface FeedbackRequest {
  user_id: string;
  message_id: string;
  rating: number;
  comments?: string;
  created_by?: string;
  modified_by?: string;
}
