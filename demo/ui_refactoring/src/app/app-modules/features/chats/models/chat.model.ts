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
}

export type ChatResponse = ChatMessageVM;

export interface HomePromptDTO {
  id: number;
  title: string;
  description?: string;
  prompt: string;
  serviceName?: string;
}