import { computed, inject, Injectable, signal } from '@angular/core';
import { ActorType } from '../../../../_shared/constants/actor-type';
import { ChatMessageDTO, ChatQueryDTO, ChatResponse } from '../models/chat.model';
import { ChatService } from './chat.service';
import { firstValueFrom } from 'rxjs';
import { Router } from '@angular/router';
import { AuthService } from '../../../../_shared/messaging-service/auth.service';
import { AuthUser } from '../../../../_shared/messaging-service/auth-user';
import { ConversationsVM } from '../models/conversation';
import { MessageFeedbackVM, FeedbackResultVM, FeedbackDTO } from '../models/message-feedabck';
import { FeedbackRating } from '../../../../_shared/constants/feedback-rating';
import { ServiceHierarchyVM } from '../models/service-hierarchy';

@Injectable({
  providedIn: 'root',
})
export class ChatStore {
  /**
   * The main store for chat state management. It holds the current messages, loading states, selected conversation, and list of conversations.
   * It provides methods to manipulate this state and interact with the ChatService for API calls.
   */
  readonly messages = signal<ChatResponse[]>([]);
  /**
   * Enable/disable streaming for chat responses. Set to true to stream, false for normal requests.
   */
  readonly enableStreaming = signal(false);
  /**
   * Indicates if a chat message is currently being sent/processed. This can be used to show loading indicators in the UI and prevent duplicate sends.
   */
  readonly loading = signal(false);
  /**
   * The ID of the currently selected conversation. This is used to determine which conversation's messages 
   * to display and where to send new messages. It can be null if no conversation is selected.
   */
  readonly selectedConversationId = signal<number | null>(null);

  readonly selectedSessionId = signal<string | null>(null);

  /**
   * The list of chat conversations available to the user. 
   * This is loaded from the backend and updated when new conversations are created. 
   * Each conversation has an ID, name, and other metadata.
   */
  readonly chatConversations = signal<ConversationsVM[]>([]);
  readonly hasMoreMessages = signal(false);
  readonly hasMoreConversations = signal(false);
  readonly loadingConversations = signal(false);
  readonly feedbackResult = signal<FeedbackResultVM | null>(null);
  readonly serviceHierarchies = signal<ServiceHierarchyVM[]>([]);
  private hierarchiesLoaded = false;

  private readonly pendingApiRequests = signal(0);
  readonly isAPILoading = computed(() => this.pendingApiRequests() > 0);
  private conversationLoadToken = 0;
  private trackCounter = 0;
  private readonly messagePageSize = 10;
  private readonly conversationPageSize = 8;


  // Injecting necessary services for API calls, routing, and authentication.
  private chatService = inject(ChatService);
  private readonly router = inject(Router);
  private readonly authService = inject(AuthService<AuthUser>);


  /**
   * The currently authenticated user. This is used to associate messages with the user and 
   * can be used for permission checks or displaying user info in the UI.
   */
  readonly authUser = computed<AuthUser | null>(() => this.authService.user);

  /**
   * Adds a new message to the current list of messages.
   * @param message The message to be added. This is typically a response from the bot or a user query that has been sent.
   */
  addMessage(message: ChatResponse) {
    this.messages.update(msgs => [...msgs, message]);
  }

  setLoading(isLoading: boolean) {
    this.loading.set(isLoading);
  }
  clearFeedbackResult() {
    this.feedbackResult.set(null);
  }


  /**
   * Sets the list of messages for the current conversation.
   * @param messages The array of messages to set.
   */
  setMessages(messages: ChatResponse[]) {
    this.messages.set(messages);
  }

  /**
   * Clears all messages from the current conversation.
   */
  clearMessages() {
    this.messages.set([]);
    this.hasMoreMessages.set(false);
  }

  /**
   * Updates API loading by reference count to support concurrent requests safely.
   * @param isLoading True to increment pending request count, false to decrement.
   */
  setIsAPILoading(isLoading: boolean) {
    this.pendingApiRequests.update(count => {
      if (isLoading) {
        return count + 1;
      }

      return Math.max(0, count - 1);
    });
  }

  /**
   * Sets the list of chat conversations.
   * @param conversations The array of chat conversations to set.
   */
  setChatConversations(conversations: ConversationsVM[]) {
    this.chatConversations.set(conversations);
  }

  appendChatConversations(conversations: ConversationsVM[]) {
    const existing = new Set(this.chatConversations().map(conversation => conversation.id));
    const newConversations = conversations.filter(conversation => !existing.has(conversation.id));
    this.chatConversations.update(current => [...current, ...newConversations]);
  }

  /**
   * Adds a user query to the current conversation.
   * @param chatQuery The user query to be added.
   */
  addUserQueryToCurrentConversation(chatQuery: ChatQueryDTO) {
    const tempMessageId = `tmp-${chatQuery.queryId}`;
    const chatUserQry: ChatResponse = {
      id: 0,
      messageId: tempMessageId,
      trackId: `${tempMessageId}_User`,
      localTempId: chatQuery.queryId,
      queryId: chatQuery.queryId,
      conversationId: this.selectedConversationId() ?? 0,
      chatSessionId: this.selectedSessionId() ?? '',
      role: 'User',
      answer: chatQuery.userQuery,
      content: chatQuery.userQuery,
      timestamp: new Date()
    };
    this.addMessage(chatUserQry);
  }

  startNewConversation() {
    this.selectedConversationId.set(null);
    this.selectedSessionId.set(null);
    this.clearMessages();
  }

  async loadConversation(conversationId: number) {
    const user = this.authUser();
    const userId = user?.userInfoId;
    if (!userId) {
      return;
    }

    const isSameConversation = this.selectedConversationId() === conversationId;
    this.selectedConversationId.set(conversationId);

    // Only reset the ChatSessionId when switching to a different conversation.
    // When navigating to the same conversation (e.g. post-stream route update),
    // preserve the session so the backend maintains the correct context.
    if (!isSameConversation) {
      this.selectedSessionId.set(null);
    }

    await this.loadConversationMessages(conversationId, userId);
  }

  selectConversation(conversationId: number) {
    this.router.navigate(['/features/page/chats', conversationId]);
  }

  startNewChat() {
    this.router.navigate(['/features/page/chats']);
  }

  private ensureSelectedConversationId(): number | null {
    return this.selectedConversationId();
  }

  private ensureChatSessionId(): string | null {
    return this.selectedSessionId();
  }

  async loadConversations(reset = true) {
    if (this.loadingConversations()) {
      return;
    }

    const userId = this.authUser()?.userInfoId;
    if (!userId) {
      return;
    }

    this.loadingConversations.set(true);
    this.setIsAPILoading(true);
    try {
      const response = await firstValueFrom(this.chatService.loadConversations(userId, this.conversationPageSize));
      if (response.success) {
        const page = response.result;
        const conversations = (page?.conversations ?? []) as ConversationsVM[];
        if (reset) {
          this.setChatConversations(conversations);
        } else {
          this.appendChatConversations(conversations);
        }
        this.hasMoreConversations.set(Boolean(page?.hasMore));
      }
    } catch (error) {
      console.error('Failed to load conversations', error);
    } finally {
      this.loadingConversations.set(false);
      this.setIsAPILoading(false);
    }
  }

  async loadMoreConversations() {
    if (this.loadingConversations() || !this.hasMoreConversations()) {
      return;
    }

    const userId = this.authUser()?.userInfoId;
    if (!userId) {
      return;
    }

    const conversations = this.chatConversations();
    const lastId = conversations.length > 0 ? conversations[conversations.length - 1].id : undefined;

    this.loadingConversations.set(true);
    this.setIsAPILoading(true);
    try {
      const response = await firstValueFrom(
        this.chatService.loadConversations(userId, this.conversationPageSize, lastId)
      );

      if (!response.success) {
        return;
      }

      const page = response.result;
      this.appendChatConversations((page?.conversations ?? []) as ConversationsVM[]);
      this.hasMoreConversations.set(Boolean(page?.hasMore));
    } catch (error) {
      console.error('Failed to load more conversations', error);
    } finally {
      this.loadingConversations.set(false);
      this.setIsAPILoading(false);
    }
  }

  private async loadConversationMessages(conversationId: number, userId: number) {
    if (!conversationId) {
      this.clearMessages();
      return;
    }

    const token = ++this.conversationLoadToken;
    this.setIsAPILoading(true);

    try {
      const response = await firstValueFrom(
        this.chatService.loadConversationMessages(conversationId, userId, undefined, this.messagePageSize)
      );

      if (token !== this.conversationLoadToken) {
        return;
      }

      if (response.success) {
        const messages = (response.result?.messages ?? []).map(dto => this.toChatMessageVM(dto));
        this.setMessages(messages);
        this.hasMoreMessages.set(Boolean(response.result?.hasMore));
      } else {
        this.clearMessages();
      }
    } catch (error) {
      if (token === this.conversationLoadToken) {
        this.clearMessages();
      }
      console.error('Failed to load conversation messages', error);
    } finally {
      if (token === this.conversationLoadToken) {
        this.setIsAPILoading(false);
      }
    }
  }

  async loadMoreMessages() {
    const conversationId = this.selectedConversationId();
    const userId = this.authUser()?.userInfoId;
    
    if (!conversationId || !this.hasMoreMessages() || !userId) {
      return;
    }

    this.setIsAPILoading(true);
    try {
      const current = this.messages();
      const oldestId = current
        .map(m => Number(m.id))
        .filter(id => !Number.isNaN(id))
        .reduce((min, id) => Math.min(min, id), Number.POSITIVE_INFINITY);

      const lastId = Number.isFinite(oldestId) ? oldestId : undefined;
      const response = await firstValueFrom(
        this.chatService.loadConversationMessages(conversationId, userId, lastId, this.messagePageSize)
      );

      if (!response.success) {
        return;
      }

      const older = (response.result?.messages ?? []).map(dto => this.toChatMessageVM(dto));
      const identityKey = (m: ChatResponse) => m.id > 0 ? `id:${m.id}` : `msg:${m.messageId ?? ''}`;
      const existingKeys = new Set(current.map(identityKey));
      const merged = [...older.filter(m => !existingKeys.has(identityKey(m))), ...current];

      this.setMessages(merged);
      this.hasMoreMessages.set(Boolean(response.result?.hasMore));
    } catch (error) {
      console.error('Failed to load more messages', error);
    } finally {
      this.setIsAPILoading(false);
    }
  }

  /**
   * Sends a chat message using the provided chat query.
   * 
   * This method sets loading states, ensures a conversation is selected,
   * updates the chat query with conversation/thread IDs, adds the user's query
   * to the current conversation, and sends the message via the chat service.
   * If the response is successful, it adds the bot's response to the conversation,
   * resolves the pending user message, and updates the selected conversation if needed.
   * Loading states are reset after completion.
   * 
   * @param chatQuery The chat query data transfer object containing message details.
   * @returns A Promise that resolves when the message sending process is complete.
   * 
   * @remarks
   * The `void` keyword before `this.loadConversations(true);` is used to explicitly ignore
   * the returned Promise, indicating that the result is not awaited or handled.
   */
  async sendMessage(chatQuery: ChatQueryDTO) {
    // Check if streaming is enabled
    if (this.enableStreaming()) {
      return this.sendMessageWithStreaming(chatQuery);
    }

    // Original non-streaming implementation
    this.setIsAPILoading(true);
    this.setLoading(true);

    try {
      const conversationId = this.ensureSelectedConversationId();
      chatQuery.threadId = conversationId ?? 0;
      chatQuery.conversationId = conversationId ?? undefined;
      chatQuery.chatSessionId = this.ensureChatSessionId() ?? undefined;

      this.addUserQueryToCurrentConversation(chatQuery);

      const response = await firstValueFrom(this.chatService.sendChatMessage(chatQuery));
      if (response.success && response.result) {
        const botResponse = this.toChatMessageVM(response.result as ChatMessageDTO);

        if (!this.selectedConversationId() && botResponse.conversationId) {
          // New conversation created - update state and navigate
          this.selectedConversationId.set(botResponse.conversationId);
          this.router.navigate(['/features/page/chats', botResponse.conversationId]);
          void this.loadConversations(true);
        }

        if (botResponse.chatSessionId) {
          this.selectedSessionId.set(botResponse.chatSessionId);
        }

        this.addMessage(botResponse);
        this.resolvePendingUserMessage(chatQuery.queryId);
      }
    } catch (error) {
      console.error('Failed to send message', error);
    } finally {
      this.setIsAPILoading(false);
      this.setLoading(false);
    }
  }

  /**
   * Sends a message with streaming enabled for progressive response updates.
   * Creates a placeholder bot message that gets updated as chunks arrive.
   */
  private async sendMessageWithStreaming(chatQuery: ChatQueryDTO) {
    this.setIsAPILoading(true);
    this.setLoading(true);

    try {
      const conversationId = this.ensureSelectedConversationId();
      const chatSessionId = this.ensureChatSessionId();
      chatQuery.threadId = conversationId ?? 0;
      chatQuery.conversationId = conversationId ?? undefined;
      chatQuery.chatSessionId = chatSessionId ?? undefined;

      // Add user message
      this.addUserQueryToCurrentConversation(chatQuery);

      const streamingMessageId = `streaming-${Date.now()}`;
      let streamingMessageAdded = false;

      // Start streaming
      await this.chatService.streamChatResponse(
        chatQuery,
        (chunk: string, fullContent: string) => {
          if (!streamingMessageAdded) {
            const streamingMessage: ChatResponse = {
              id: 0,
              messageId: streamingMessageId,
              trackId: streamingMessageId,
              conversationId: conversationId ?? 0,
              role: 'Assistant',
              answer: fullContent,
              content: fullContent,
              timestamp: new Date(),
              isStreaming: true,
              chatSessionId: chatSessionId ?? ''
            };
            this.addMessage(streamingMessage);
            streamingMessageAdded = true;
          } else {
            this.updateStreamingMessage(streamingMessageId, fullContent);
          }
        },
        // onComplete: Finalize the message with server data
        (messageData: ChatMessageDTO) => {
          const finalMessage = this.toChatMessageVM(messageData);
          
          // Update conversation if this was a new chat
          if (!this.selectedConversationId() && finalMessage.conversationId) {
            this.selectedConversationId.set(finalMessage.conversationId);
            this.router.navigate(['/features/page/chats', finalMessage.conversationId]);
            void this.loadConversations(true);
          }

          if (finalMessage.chatSessionId) {
            this.selectedSessionId.set(finalMessage.chatSessionId);
          }
          
          // Replace streaming message with final message and clear all loading states immediately
          this.finalizeStreamingMessage(streamingMessageId, finalMessage);
          this.resolvePendingUserMessage(chatQuery.queryId);
          this.setIsAPILoading(false);
          this.setLoading(false);
        },
        // onError: Handle streaming errors
        (error: Error) => {
          console.error('Streaming error:', error);
          if (streamingMessageAdded) {
            this.markStreamingMessageAsError(streamingMessageId);
          }
        },
        // onThinkingChange: show/hide separate Generating... indicator while waiting for generate node
        (isThinking: boolean) => {
          if (streamingMessageAdded) {
            this.setStreamingMessageThinking(streamingMessageId, isThinking);
          }
        }
      );
    } catch (error) {
      console.error('Failed to send streaming message', error);
    } finally {
      this.setIsAPILoading(false);
      this.setLoading(false);
    }
  }

  /**
   * Updates a streaming message's content as chunks arrive
   */
  private updateStreamingMessage(messageId: string, content: string) {
    this.messages.update(messages =>
      messages.map(msg =>
        msg.messageId === messageId
          ? { ...msg, answer: content, content, isStreaming: true }
          : msg
      )
    );
  }

  private setStreamingMessageThinking(messageId: string, isThinking: boolean) {
    this.messages.update(messages =>
      messages.map(msg =>
        msg.messageId === messageId
          ? { ...msg, isThinking }
          : msg
      )
    );
  }

  /**
   * Replaces the streaming placeholder with the final message from server
   */
  private finalizeStreamingMessage(streamingMessageId: string, finalMessage: ChatResponse) {
    this.messages.update(messages =>
      messages.map(msg =>
        msg.messageId === streamingMessageId
          // Preserve the streaming placeholder's trackId so Angular updates the existing
          ? { ...finalMessage, isStreaming: false, trackId: msg.trackId }
          : msg
      )
    );
  }

  /**
   * Marks a streaming message as failed
   */
  private markStreamingMessageAsError(messageId: string) {
    const userMessage = 'Something went wrong. Please try again with a new chat.';
    this.messages.update(messages =>
      messages.map(msg =>
        msg.messageId === messageId
          ? { 
              ...msg, 
              isStreaming: false, 
              isError: true,
              answer: userMessage,
              content: userMessage
            }
          : msg
      )
    );
  }

  private resolvePendingUserMessage(localTempId: string) {
    this.messages.update(messages =>
      messages.map(message =>
        message.localTempId === localTempId
          ? { ...message, isPending: false }
          : message
      )
    );
  }

  private toChatMessageVM(dto: ChatMessageDTO): ChatResponse {
    const isUser = dto.actor === ActorType.User;
    const uniqueTrackId = isUser
      ? `${dto.messageId}_User_t${++this.trackCounter}`
      : `${dto.messageId || 'msg'}_t${++this.trackCounter}`;
    return {
      id: dto.id,
      messageId: dto.messageId,
      trackId: uniqueTrackId,
      conversationId: Number(dto.conversationId),
      role: isUser ? 'User' : 'Assistant',
      answer: dto.content,
      content: dto.content,
      timestamp: dto.createdAt,
      refDocs: dto.refDocs?.length ? dto.refDocs : this.mapChunkDocs(dto),
      hasFeedback: Boolean(dto.feedback),
      feedbackId: dto.feedback?.id,
      isLiked: dto.feedback?.rating === FeedbackRating.Positive,
      feedbackRating: dto.feedback?.rating,
      feedbackComments: dto.feedback?.comments,
      chatSessionId: dto.chatSessionId
    };
  }

  private mapChunkDocs(dto: ChatMessageDTO) {
    if (!dto.chunks_used?.length) {
      return [];
    }

    return dto.chunks_used.map(chunk => ({
      title: chunk.file_name || 'Unknown',
      url: '',
      pageNumbers: chunk.page_number ? `Page ${chunk.page_number}` : '',
    }));
  }

  async loadServiceHierarchies(): Promise<void> {
    if (this.hierarchiesLoaded) return;
    try {
      const response = await firstValueFrom(this.chatService.getServiceHierarchies());
      if (response.success && response.result) {
        this.serviceHierarchies.set(response.result);
        this.hierarchiesLoaded = true;
      }
    } catch (error) {
      console.error('Failed to load service hierarchies', error);
    }
  }

  async postFeedback(feedback: FeedbackDTO) {
    this.feedbackResult.set(null);
    
    const userId = this.authUser()?.username;
    const messageId = feedback.messageId;
    if (!messageId) {
      return;
    }

    feedback.userId = String(userId ?? '');

    try {
      const response = await firstValueFrom(this.chatService.postFeedback(feedback));
      if (response.result) {
        //update local message state to reflect feedback given
        this.messages.update(messages =>
          messages.map(msg =>
            msg.messageId === messageId
              ? { ...msg, hasFeedback: true, 
                isLiked: feedback.rating === FeedbackRating.Positive,
                feedbackComments: feedback.comments,
                feedbackRating: feedback.rating,
                feedbackCategory: feedback.category,
                feedbackFunctionId: feedback.functionId,
                feedbackSubFunctionId: feedback.subFunctionId,
                feedbackServiceId: feedback.serviceId
              }
              : msg
          )
        );
        const feedBackResult: FeedbackResultVM = {
          success: true,
          message:  'Thank you for your feedback!'
        };
        this.feedbackResult.set(feedBackResult);
      }
    } catch (error) {
      console.error('Failed to post feedback', error);
    } 
  }
}
