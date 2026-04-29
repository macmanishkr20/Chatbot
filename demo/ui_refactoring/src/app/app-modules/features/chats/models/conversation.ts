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
}

export interface ConversationRequestVM extends PaginationVM {
    id: number;
    userId?: number;
    lastFetchedMessageId?: number;
    lastFetchedConversationId?: number;
}