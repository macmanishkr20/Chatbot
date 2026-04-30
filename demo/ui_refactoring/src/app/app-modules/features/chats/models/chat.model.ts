import { Signal, WritableSignal } from "@angular/core";
import { ActorType } from "../../../../_shared/constants/actor-type";
import { MessageFeedbackVM } from "./message-feedabck";
import { FeedbackRating } from "../../../../_shared/constants/feedback-rating";

export type Role = 'User' | 'Assistant';
export type SideBarItemType = 'action' | 'group' | 'link';

export interface PaginationVM {
  totalCount: number;
  pageSize: number;
  pageCount?: number;
}


export interface NavItem extends GenericResponse {
  icon?: string;              // e.g., 'bi bi-house'
  path?: string;              // for single routing menu
  externalUrl?: string;       // optional for external links
  badge?: string | number;    // optional small badge
  children?: Signal<NavItem[]>;       // if present => collapsible group
  exact?: boolean;            // exact match active
  action?: () => void;           // action to perform on click (navigate or custom)
  type: SideBarItemType;        // type of the sidebar item (action or group)
  expanded?: WritableSignal<boolean>; // track expanded state for groups
  showInSidebar: boolean;
}
export interface GenericResponse {
  id: string;                 // unique ID for tracking open state
  name: string;              // menu text
  code: string;               // unique code for permissions
  createdAt?: Date | string;
  updatedAt?: Date | string;
}

//Finalized Chat Models with Pagination and Feedback
 export interface ChatQueryDTO {
     userQuery: string;
     userEmail?: string;
     queryId: string;
     threadId: number;
     conversationId?: number;
     chatSessionId?: string;
}

export interface ChatMessageDTO {
    id: number;
    messageId: string;
    conversationId: string;
    actor: ActorType;
    content: string;
    chatSessionId?: string;

    parentMessageId?: number;
    createdAt: Date | string;
    modifiedAt?: Date | string;

    metaData: MessageMetaDataVM[];
    refDocs?: ChatRefDocsVM[];
    chunks_used?: ChatChunkUsedVM[];
    feedback?: MessageFeedbackVM;

}



export interface ChatMessagePaginationVM {
    hasMore: boolean;
    messages: ChatMessageDTO[];
}

export interface MessageMetaDataVM {
   id: number;
   messageId: number;
   key: string;
   value: string;
   isActive?: boolean;
   createdAt: Date | string;
   modifiedAt?: Date | string;
}

export interface ChatRefDocsVM {
   title?: string;
   url?: string;
   pageNumbers?: string;
}

export interface ChatChunkUsedVM {
  file_name?: string;
  page_number?: number;
}

export interface ChatMessageVM {
  id: number;
  messageId: string;
  trackId?: string;
  queryId?: string;
  conversationId: number;
  chatSessionId?: string;
  role: Role;
  answer: string;
  content?: string;
  timestamp: Date | string;
  avatarUrl?: string;
  name?: string;
  refDocs?: ChatRefDocsVM[];
  isStreaming?: boolean;
  isThinking?: boolean;
  isPending?: boolean;
  isError?: boolean;
  localTempId?: string;
  hasFeedback?: boolean;
  isLiked?: boolean;
  feedbackId?: number;
  feedbackComments?: string;
  feedbackRating?: FeedbackRating;
  feedbackCategory?: string;
  feedbackFunctionId?: number;
  feedbackSubFunctionId?: number;
  feedbackServiceId?: number;
  // ── Ported from menabot-ui (drives Thinking / Deep Search / Citations / Suggestive Actions / inline edit) ──
  userMessageIndex?: number;
  thinkingSteps?: ThinkingStep[];
  thinkingCollapsed?: boolean;
  deepSearchSteps?: string[];
  deepSearchCollapsed?: boolean;
  suggestiveActions?: SuggestiveAction[];
  citations?: Citation[];
  conversationTitle?: string | null;
  isEditing?: boolean;
  editText?: string;
}

export type ChatResponse = ChatMessageVM;

export interface HomePromptDTO {
  id: number;
  title: string;
  description?: string;
  prompt: string;
  serviceName?: string;
}

// ──────────────────────────────────────────────────────────────────────
// menabot-ui /chat protocol — kept verbatim so the SSE handler can be
// a direct port. Components use ChatMessageVM above as the view model;
// these types belong to the API layer.
// ──────────────────────────────────────────────────────────────────────

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

export interface DeepSearchEvent {
  type: 'deep_search';
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
  requires_function_selection?: boolean;
  function_required_reason?: string | null;
  function_hint?: string | null;
  function_candidates?: string[];
  selected_function?: string | null;
}

export type SSEEvent = ThoughtEvent | ContentEvent | DeepSearchEvent | FinalEvent;

export interface SuggestiveAction {
  short_title: string;
  description?: string;
}

export interface Citation {
  indexes: number[];
  source: string;
  isUrl: boolean;
}

export interface ThinkingStep {
  node: string;
  message: string;
  state: 'pending' | 'running' | 'done';
}

/** Stored conversation row from /conversations/{user_id}. */
export interface StoredConversation {
  Id: number;
  UserId: string;
  Title: string;
  ChatSessionId?: string | null;
  ConversationType: string;
  CreatedAt: string;
  ModifiedAt: string;
}

/** Stored message row from /conversations/{user_id}/{chat_id}/messages. */
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
  content_type?: 'qa_pair' | 'document';
}

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
  content_type?: 'qa_pair' | 'document';
}

export interface RegenerateRequest {
  user_id: string;
  chat_id: string;
  chat_session_id: string;
}

export interface CancelRequest {
  user_id: string;
  chat_session_id: string;
}

export interface RenameRequest {
  title: string;
}

export interface FeedbackRequest {
  user_id: string;
  message_id: string;
  rating: number;
  comments?: string;
  created_by?: string;
  modified_by?: string;
}
