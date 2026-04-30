import { ChannelType } from "../../../../_shared/constants/channel-type";
import { PaginationVM } from "./chat.model";

export interface ConversationPaginationVM {
    hasMore: boolean;
    conversations: ConversationsVM[];
}

export interface ConversationsVM {
    id: number;
    title: string;
    clientType: ChannelType;
    createdAt: Date | string;
    modifiedAt?: Date | string;
    /**
     * Original LangGraph chat_session_id from menabot-ui's backend.
     * Used to restore the LangGraph thread for edit/regenerate.
     */
    chatSessionId?: string | null;
}

export interface ConversationRequestVM extends PaginationVM {
    id: number;
    userId?: number;
    lastFetchedMessageId?: number;
    lastFetchedConversationId?: number;
}