import { computed, inject, Injectable, signal } from '@angular/core';
import { Router } from '@angular/router';
import { firstValueFrom } from 'rxjs';
import { AuthService } from '../../../../_shared/messaging-service/auth.service';
import { AuthUser } from '../../../../_shared/messaging-service/auth-user';
import { FeedbackRating } from '../../../../_shared/constants/feedback-rating';
import { ChatService } from './chat.service';
import {
  ChatResponse,
  Citation,
  DeepSearchEvent,
  FinalEvent,
  SSEEvent,
  SuggestiveAction,
  StoredConversation,
  ThinkingStep,
} from '../models/chat.model';
import { ConversationsVM } from './../models/conversation';
import { ChannelType } from '../../../../_shared/constants/channel-type';
import { FeedbackDTO, FeedbackResultVM } from '../models/message-feedabck';
import { ServiceHierarchyVM } from '../models/service-hierarchy';

/**
 * Central chat state manager.
 *
 * This is a direct port of menabot-ui's `ChatService` (services/chat.service.ts),
 * adapted to ui_refactoring's auth (`AuthService<AuthUser>`) and routing
 * (`/features/page/chats/:id`). All /chat pipeline behaviour — streaming with
 * smooth drip, thinking steps, deep search, edit, regenerate, cancel,
 * suggestive actions, function chips, citations and feedback — matches
 * menabot-ui exactly.
 */
@Injectable({ providedIn: 'root' })
export class ChatStore {
  private readonly chatService = inject(ChatService);
  private readonly router = inject(Router);
  private readonly authService = inject(AuthService<AuthUser>);

  // ── Reactive state (signals) ──

  /** All messages in the current conversation. */
  readonly messages = signal<ChatResponse[]>([]);

  /** Conversation list (sidebar). */
  readonly chatConversations = signal<ConversationsVM[]>([]);

  /** Active LangGraph chat_session_id (null = new chat). */
  readonly selectedSessionId = signal<string | null>(null);

  /** Active SQL chat_id (null until first response). */
  readonly selectedConversationId = signal<number | null>(null);

  /** Conversation title (auto-generated or user-set). */
  readonly conversationTitle = signal<string | null>(null);

  /** Whether a stream is currently active. */
  readonly isStreaming = signal(false);

  /** UI loading flag (mirror of isStreaming for legacy components). */
  readonly loading = computed(() => this.isStreaming());

  /** Conversation list loading. */
  readonly loadingConversations = signal(false);

  /** Pagination — kept for legacy chat-sidebar `Load more` button. Always false now (full list returned). */
  readonly hasMoreConversations = signal(false);

  /** Pagination — kept for legacy chat-window scroll. Always false (full conversation returned). */
  readonly hasMoreMessages = signal(false);

  /** Concurrent API loading reference count, for UI spinners. */
  private readonly pendingApiRequests = signal(0);
  readonly isAPILoading = computed(() => this.pendingApiRequests() > 0);

  /** Currently selected MENA function chip (e.g. 'AWS', 'Talent'). */
  readonly selectedFunction = signal<string | null>(null);

  /** Glow / shimmer the function chips below the input. */
  readonly chipsHighlighted = signal(false);

  /** Optional reason text the backend gave for asking to (re)select. */
  readonly functionPromptReason = signal<string | null>(null);

  /** Last error message (null = no error). */
  readonly error = signal<string | null>(null);

  /** Toast feedback result (used by chat-window for toast notifications). */
  readonly feedbackResult = signal<FeedbackResultVM | null>(null);

  /** Service hierarchies for the categorised feedback form. */
  readonly serviceHierarchies = signal<ServiceHierarchyVM[]>([]);

  /** Streaming toggle — kept for legacy chat-container; menabot-ui flow is always streaming. */
  readonly enableStreaming = signal(true);

  /** Authenticated user (used by sidebar and other components). */
  readonly authUser = computed<AuthUser | null>(() => this.authService.user);

  /** User identity sent to the backend as `user_id`. Falls back to a demo identity. */
  readonly userId = computed(() => {
    const user = this.authService.user;
    return (user && user.email) ? user.email : 'demo.user@gds.ey.com';
  });

  /** Number of user messages (for edit indexing). */
  readonly userMessageCount = computed(() =>
    this.messages().filter(m => m.role === 'User').length,
  );

  // ── Internal ──
  private hierarchiesLoaded = false;
  private abortController: AbortController | null = null;
  private userMsgCounter = 0;
  private pendingResendQuery: string | null = null;
  private trackCounter = 0;

  // ── Smooth streaming (word-by-word drip buffer) ──
  private contentQueue = '';
  private dripTimerId: ReturnType<typeof setTimeout> | null = null;
  private dripAssistantId: string | null = null;

  // ── Public API ──

  /** Start a new chat — clears messages and generates a new session ID. */
  newChat(): void {
    this.messages.set([]);
    this.selectedSessionId.set(this.generateSessionId());
    this.selectedConversationId.set(null);
    this.conversationTitle.set(null);
    this.error.set(null);
    this.userMsgCounter = 0;
    this.selectedFunction.set(null);
    this.chipsHighlighted.set(true);
    this.functionPromptReason.set(null);
    this.pendingResendQuery = null;
  }

  /** Reset state when entering a fresh chat URL (matches legacy method name used by chat-window). */
  startNewConversation(): void {
    this.newChat();
  }

  /** Navigate to /features/page/chats (called by sidebar "New Chat"). */
  startNewChat(): void {
    this.router.navigate(['/features/page/chats']);
  }

  /** Function chip selection. */
  selectFunction(code: string): void {
    this.selectedFunction.set(code);
    this.chipsHighlighted.set(false);
    this.functionPromptReason.set(null);

    const pending = this.pendingResendQuery;
    this.pendingResendQuery = null;
    if (pending && !this.isStreaming()) {
      void this.sendUserMessage(pending);
    }
  }

  clearFunction(): void {
    this.selectedFunction.set(null);
    this.pendingResendQuery = null;
  }

  /**
   * Send a user message and stream the response.
   * Call signature kept compatible with the legacy `sendMessage(chatQuery)` —
   * we accept either a raw text or a `ChatQueryDTO`-shaped object.
   */
  async sendMessage(input: string | { userQuery?: string }): Promise<void> {
    const text = typeof input === 'string' ? input : (input?.userQuery ?? '');
    return this.sendUserMessage(text);
  }

  private async sendUserMessage(text: string): Promise<void> {
    if (this.isStreaming() || !text.trim()) return;

    this.pendingResendQuery = null;

    if (!this.selectedSessionId()) {
      this.selectedSessionId.set(this.generateSessionId());
    }

    const userMsg: ChatResponse = {
      id: 0,
      messageId: this.generateId(),
      trackId: `user_t${++this.trackCounter}`,
      role: 'User',
      conversationId: this.selectedConversationId() ?? 0,
      chatSessionId: this.selectedSessionId() ?? '',
      answer: text.trim(),
      content: text.trim(),
      timestamp: new Date(),
      userMessageIndex: this.userMsgCounter++,
    };
    this.messages.update(msgs => [...msgs, userMsg]);

    const fn = this.selectedFunction();
    await this.streamResponse({
      input_type: 'ask',
      user_input: text.trim(),
      is_free_form: true,
      user_id: this.userId(),
      chat_session_id: this.selectedSessionId(),
      chat_id: this.selectedConversationId() ? String(this.selectedConversationId()) : undefined,
      function: fn ? [fn] : [],
      sub_function: [],
      source_url: [],
      start_date: '',
      end_date: '',
      content_type: 'qa_pair',
    });
  }

  /** Edit a user message at the given index and re-run from that point. */
  async editMessage(messageIndex: number, newText: string): Promise<void> {
    if (this.isStreaming() || !newText.trim()) return;

    const msgs = this.messages();
    const userMsgs = msgs.filter(m => m.role === 'User');
    if (messageIndex < 0 || messageIndex >= userMsgs.length) return;

    const editedUserMsg = userMsgs[messageIndex];
    const editPos = msgs.indexOf(editedUserMsg);
    if (editPos === -1) return;

    const backendIndex = msgs.slice(0, editPos + 1).filter(m => m.role === 'User').length - 1;
    const kept = msgs.slice(0, editPos);
    const updatedUserMsg: ChatResponse = {
      ...editedUserMsg,
      content: newText.trim(),
      answer: newText.trim(),
      isEditing: false,
    };
    kept.push(updatedUserMsg);

    this.messages.set(kept);
    this.userMsgCounter = backendIndex + 1;

    const fn = this.selectedFunction();
    await this.streamResponse(undefined, {
      user_id: this.userId(),
      chat_session_id: this.selectedSessionId()!,
      message_index: backendIndex,
      new_input: newText.trim(),
      is_free_form: true,
      function: fn ? [fn] : [],
      sub_function: [],
      source_url: [],
      start_date: '',
      end_date: '',
      content_type: 'qa_pair',
    });
  }

  /** Regenerate the last assistant response. */
  async regenerate(): Promise<void> {
    if (this.isStreaming() || !this.selectedConversationId()) return;

    const msgs = this.messages();
    const lastIdx = msgs.length - 1;
    if (msgs[lastIdx]?.role === 'Assistant') {
      this.messages.set(msgs.slice(0, lastIdx));
    }

    await this.streamResponse(undefined, undefined, {
      user_id: this.userId(),
      chat_id: String(this.selectedConversationId()),
      chat_session_id: this.selectedSessionId()!,
    });
  }

  /** Cancel the current in-flight stream. */
  cancelStream(): void {
    this.abortController?.abort();
    if (this.dripAssistantId) {
      this.flushContentQueue(this.dripAssistantId);
    }
    if (this.selectedSessionId()) {
      this.chatService.cancelChat({
        user_id: this.userId(),
        chat_session_id: this.selectedSessionId()!,
      }).subscribe({ error: () => { /* swallow — server may already have closed */ } });
    }
    this.isStreaming.set(false);
  }

  /** Toggle a user message into edit mode. */
  toggleEdit(msgId: string): void {
    this.messages.update(msgs =>
      msgs.map(m => {
        if (m.messageId === msgId && m.role === 'User') {
          return { ...m, isEditing: !m.isEditing, editText: m.content ?? m.answer };
        }
        return { ...m, isEditing: false };
      }),
    );
  }

  cancelEdit(msgId: string): void {
    this.messages.update(msgs =>
      msgs.map(m => (m.messageId === msgId ? { ...m, isEditing: false } : m)),
    );
  }

  // ── Conversations ──

  /** Load the conversation list from the FastAPI backend. */
  async loadConversations(_reset = true): Promise<void> {
    if (this.loadingConversations()) return;

    this.loadingConversations.set(true);
    this.setIsAPILoading(true);

    try {
      const res = await firstValueFrom(this.chatService.getConversations(this.userId()));
      const items: ConversationsVM[] = (res?.data ?? []).map(c => this.toConversationVM(c));
      this.chatConversations.set(items);
      // FastAPI returns the full list — no further pages.
      this.hasMoreConversations.set(false);
    } catch (err) {
      console.error('Failed to load conversations:', err);
    } finally {
      this.loadingConversations.set(false);
      this.setIsAPILoading(false);
    }
  }

  /** No-op: kept for legacy chat-sidebar "Load more" button (FastAPI returns the full list). */
  async loadMoreConversations(): Promise<void> {
    return;
  }

  /** Load messages for a conversation by SQL chat_id, navigating to the URL too. */
  selectConversation(conversationId: number): void {
    this.router.navigate(['/features/page/chats', conversationId]);
  }

  /** Load a conversation (called by chat-window on route param change). */
  async loadConversation(conversationId: number): Promise<void> {
    if (!conversationId) {
      this.clearMessages();
      return;
    }

    const isSame = this.selectedConversationId() === conversationId;
    this.selectedConversationId.set(conversationId);

    // Find the matching conversation row to recover the original
    // ChatSessionId — needed so edit/regenerate hit the right LangGraph thread.
    const row = await this.findStoredConversation(conversationId);
    if (!isSame) {
      this.selectedSessionId.set(row?.ChatSessionId || String(conversationId));
    }
    this.conversationTitle.set(row?.Title ?? null);

    // If we already have in-memory messages for this thread (e.g. the SSE final
    // event just routed us here from the welcome screen), skip the reload —
    // the stored copy may not yet include the latest assistant turn anyway.
    const haveLocal = this.messages().some(m => m.conversationId === conversationId);
    if (haveLocal && isSame) return;

    await this.loadMessages(conversationId);
  }

  /** Load messages — full list returned by FastAPI; no pagination. */
  private async loadMessages(chatId: number): Promise<void> {
    this.setIsAPILoading(true);
    try {
      const res = await firstValueFrom(this.chatService.getMessages(this.userId(), chatId));
      const stored = res?.data ?? [];

      const msgs: ChatResponse[] = [];
      this.userMsgCounter = 0;
      for (const s of stored) {
        if (s.UserPrompt) {
          msgs.push({
            id: s.Id,
            messageId: s.MessageId || this.generateId(),
            trackId: `${s.MessageId || s.Id}_User_t${++this.trackCounter}`,
            role: 'User',
            conversationId: s.ConversationSessionId,
            answer: s.UserPrompt,
            content: s.UserPrompt,
            timestamp: new Date(s.CreatedAt),
            userMessageIndex: this.userMsgCounter++,
          });
        }
        if (s.AiContentFreeForm) {
          let content = s.AiContentFreeForm;
          try {
            const parsed = JSON.parse(content);
            if (typeof parsed === 'string') content = parsed;
          } catch { /* keep as-is */ }
          msgs.push({
            id: s.Id,
            messageId: s.MessageId || this.generateId(),
            trackId: `${s.MessageId || s.Id}_t${++this.trackCounter}`,
            role: 'Assistant',
            conversationId: s.ConversationSessionId,
            answer: content,
            content,
            timestamp: new Date(s.CreatedAt),
            citations: this.parseCitations(content),
          });
        }
      }
      this.messages.set(msgs);
      this.hasMoreMessages.set(false);
    } catch (err) {
      console.error('Failed to load messages:', err);
      this.error.set('Failed to load conversation');
      this.clearMessages();
    } finally {
      this.setIsAPILoading(false);
    }
  }

  /** No-op: kept for legacy chat-window scroll-up handler (FastAPI returns full message list). */
  async loadMoreMessages(): Promise<void> {
    return;
  }

  /** Delete a conversation. */
  deleteConversation(conv: ConversationsVM): void {
    this.chatService.deleteConversation(this.userId(), conv.id).subscribe({
      next: () => {
        this.chatConversations.update(list => list.filter(c => c.id !== conv.id));
        if (this.selectedConversationId() === conv.id) {
          this.newChat();
          this.router.navigate(['/features/page/chats']);
        }
      },
      error: (err) => console.error('Failed to delete conversation:', err),
    });
  }

  /** Rename a conversation. */
  renameConversation(conv: ConversationsVM, newTitle: string): void {
    this.chatService.renameConversation(this.userId(), conv.id, { title: newTitle }).subscribe({
      next: () => {
        this.chatConversations.update(list =>
          list.map(c => (c.id === conv.id ? { ...c, title: newTitle } : c)),
        );
        if (this.selectedConversationId() === conv.id) {
          this.conversationTitle.set(newTitle);
        }
      },
      error: (err) => console.error('Failed to rename conversation:', err),
    });
  }

  // ── Feedback ──

  /** Service hierarchies — loaded once for the categorised feedback form. */
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

  /** Submit feedback — POSTs menabot-ui's /feedback shape. Extra ui_refactoring fields
   *  (functionId / subFunctionId / serviceId / category) are bundled into `comments`
   *  as a single human-readable suffix so nothing is lost. */
  async postFeedback(feedback: FeedbackDTO): Promise<void> {
    this.feedbackResult.set(null);

    if (!feedback.messageId) return;

    const email = this.authService.user?.email || this.userId();
    feedback.userId = email;

    const ratingNumeric =
      feedback.rating === FeedbackRating.Positive ? 1 :
      feedback.rating === FeedbackRating.Negative ? -1 : 0;

    const extras: string[] = [];
    if (feedback.category) extras.push(`category=${feedback.category}`);
    if (feedback.functionId) extras.push(`functionId=${feedback.functionId}`);
    if (feedback.subFunctionId) extras.push(`subFunctionId=${feedback.subFunctionId}`);
    if (feedback.serviceId) extras.push(`serviceId=${feedback.serviceId}`);

    const baseComment = (feedback.comments ?? '').trim();
    const tail = extras.length ? ` [${extras.join(', ')}]` : '';
    const combinedComment = (baseComment + tail).trim();

    try {
      const res = await firstValueFrom(this.chatService.submitFeedback({
        user_id: email,
        message_id: feedback.messageId,
        rating: ratingNumeric,
        comments: combinedComment || undefined,
        created_by: email,
        modified_by: email,
      }));
      const ok = !!res && res.status !== 'error';
      if (ok) {
        this.messages.update(messages =>
          messages.map(msg =>
            msg.messageId === feedback.messageId
              ? {
                  ...msg,
                  hasFeedback: true,
                  isLiked: feedback.rating === FeedbackRating.Positive,
                  feedbackRating: feedback.rating,
                  feedbackComments: feedback.comments,
                  feedbackCategory: feedback.category,
                  feedbackFunctionId: feedback.functionId,
                  feedbackSubFunctionId: feedback.subFunctionId,
                  feedbackServiceId: feedback.serviceId,
                }
              : msg,
          ),
        );
        this.feedbackResult.set({ success: true, message: 'Thank you for your feedback!' });
      }
    } catch (err) {
      console.error('Failed to post feedback', err);
      this.feedbackResult.set({ success: false, message: 'Failed to submit feedback. Please try again.' });
    }
  }

  clearFeedbackResult(): void {
    this.feedbackResult.set(null);
  }

  // ── Internal: streaming pipeline (verbatim port of menabot-ui) ──

  private async streamResponse(
    chatBody?: import('../models/chat.model').ChatRequest,
    editBody?: import('../models/chat.model').EditRequest,
    regenBody?: import('../models/chat.model').RegenerateRequest,
  ): Promise<void> {
    this.isStreaming.set(true);
    this.error.set(null);
    this.abortController = new AbortController();

    const assistantMsg: ChatResponse = {
      id: 0,
      messageId: this.generateId(),
      trackId: `assistant_t${++this.trackCounter}`,
      role: 'Assistant',
      conversationId: this.selectedConversationId() ?? 0,
      chatSessionId: this.selectedSessionId() ?? '',
      answer: '',
      content: '',
      thinkingSteps: [],
      thinkingCollapsed: false,
      deepSearchSteps: [],
      deepSearchCollapsed: false,
      isStreaming: true,
      timestamp: new Date(),
    };
    this.messages.update(msgs => [...msgs, assistantMsg]);

    let activeStepNode: string | null = null;

    try {
      const stream = editBody
        ? this.chatService.streamEdit(editBody, this.abortController.signal)
        : regenBody
          ? this.chatService.streamRegenerate(regenBody, this.abortController.signal)
          : this.chatService.streamChat(chatBody!, this.abortController.signal);

      for await (const event of stream) {
        this.processSSEEvent(event, assistantMsg.trackId!, activeStepNode);
        if (event.type === 'thought') {
          activeStepNode = event.node;
        }
      }
    } catch (err: unknown) {
      if (err instanceof Error && err.name === 'AbortError') {
        // user cancelled — expected
      } else {
        console.error('Stream error:', err);
        this.error.set('Failed to get response. Please try again.');
      }
    } finally {
      this.flushContentQueue(assistantMsg.trackId!);
      this.messages.update(msgs =>
        msgs.map(m =>
          m.trackId === assistantMsg.trackId
            ? { ...m, isStreaming: false, thinkingCollapsed: true, deepSearchCollapsed: true, answer: m.content ?? '' }
            : m,
        ),
      );
      this.isStreaming.set(false);
      this.abortController = null;
    }
  }

  private processSSEEvent(event: SSEEvent, assistantTrackId: string, _activeStepNode: string | null): void {
    switch (event.type) {
      case 'thought': {
        this.messages.update(msgs =>
          msgs.map(m => {
            if (m.trackId !== assistantTrackId) return m;
            const steps = (m.thinkingSteps ?? []).map(s =>
              s.state === 'running' ? { ...s, state: 'done' as const } : s,
            );
            steps.push({ node: event.node, message: event.message, state: 'running' });
            return { ...m, thinkingSteps: steps };
          }),
        );
        break;
      }

      case 'content': {
        this.contentQueue += event.content;
        this.dripAssistantId = assistantTrackId;
        this.startDrip();

        // Mark deep search as done once content starts arriving
        this.messages.update(msgs =>
          msgs.map(m => {
            if (m.trackId !== assistantTrackId) return m;
            if (m.deepSearchSteps?.length && !m.deepSearchDone) {
              return { ...m, deepSearchDone: true, deepSearchCollapsed: true };
            }
            return m;
          }),
        );
        break;
      }

      case 'deep_search': {
        const dsEvent = event as DeepSearchEvent;
        this.messages.update(msgs =>
          msgs.map(m => {
            if (m.trackId !== assistantTrackId) return m;
            const steps = [...(m.deepSearchSteps ?? []), dsEvent.content];
            return { ...m, deepSearchSteps: steps, deepSearchCollapsed: false };
          }),
        );
        break;
      }

      case 'final': {
        const final = event as FinalEvent;
        if (final.cancelled) return;

        const numericChatId = final.chat_id != null ? Number(final.chat_id) : null;
        if (numericChatId && !Number.isNaN(numericChatId)) {
          // First response of a brand-new conversation: capture chat_id
          // and navigate to the URL so refreshing keeps state.
          if (this.selectedConversationId() == null) {
            this.selectedConversationId.set(numericChatId);
            this.router.navigate(['/features/page/chats', numericChatId]);
          } else {
            this.selectedConversationId.set(numericChatId);
          }
        }
        if (final.conversation_title) this.conversationTitle.set(final.conversation_title);

        if (final.requires_function_selection) {
          this.chipsHighlighted.set(true);
          this.functionPromptReason.set(final.function_required_reason ?? null);
          const msgs = this.messages();
          for (let i = msgs.length - 1; i >= 0; i--) {
            if (msgs[i].role === 'User') {
              this.pendingResendQuery = msgs[i].content ?? msgs[i].answer ?? null;
              break;
            }
          }
        } else if (final.selected_function) {
          // Commented out: function chip selection on response
          // this.selectedFunction.set(final.selected_function);
        }

        if (final.function_hint && !final.requires_function_selection && !final.selected_function) {
          this.chipsHighlighted.set(true);
          this.functionPromptReason.set(final.function_hint);
        }

        const noAnswerInFinal =
          (typeof final.ai_content === 'string' && final.ai_content.trim().startsWith('[NO_ANSWER]'));
        const lastMsg = this.messages().find(m => m.trackId === assistantTrackId);
        const noAnswerInStream = (lastMsg?.content ?? '').trim().startsWith('[NO_ANSWER]');
        if ((noAnswerInFinal || noAnswerInStream) && !this.selectedFunction()) {
          this.chipsHighlighted.set(true);
          this.functionPromptReason.set('Please select a function to help me search more precisely.');
          const allMsgs = this.messages();
          for (let i = allMsgs.length - 1; i >= 0; i--) {
            if (allMsgs[i].role === 'User') {
              this.pendingResendQuery = allMsgs[i].content ?? allMsgs[i].answer ?? null;
              break;
            }
          }
        }

        const parsedActions = this.parseSuggestiveActions(final.suggestive_actions);

        this.messages.update(msgs =>
          msgs.map(m => {
            if (m.trackId !== assistantTrackId) return m;
            const steps = (m.thinkingSteps ?? []).map(s => ({ ...s, state: 'done' as const }));
            let content = m.content || (typeof final.ai_content === 'string' ? final.ai_content : (m.content ?? ''));

            const hasNoAnswer =
              (content ?? '').trim().startsWith('[NO_ANSWER]') ||
              (typeof final.ai_content === 'string' && final.ai_content.trim().startsWith('[NO_ANSWER]'));
            if (hasNoAnswer) {
              const fnCandidates = final.function_candidates ?? [];
              const fnHint = fnCandidates.length > 0 ? ` (${fnCandidates.join(', ')})` : '';
              content =
                `I wasn't able to find a specific answer for your query in the available documents${fnHint}. ` +
                'To help me get you the best result, could you please select the specific function ' +
                'your question relates to? This will allow me to search more precisely.';
            }

            const citationSource = typeof final.ai_content === 'string' ? final.ai_content : content;
            const citations = this.parseCitations(citationSource ?? '');
            const finalConvId = numericChatId && !Number.isNaN(numericChatId) ? numericChatId : m.conversationId;
            return {
              ...m,
              content,
              answer: content,
              conversationId: finalConvId,
              thinkingSteps: steps,
              messageId: final.message_id ?? m.messageId,
              suggestiveActions: parsedActions,
              conversationTitle: final.conversation_title ?? null,
              citations,
            };
          }),
        );

        // Refresh sidebar after first message of a new conversation, so the
        // newly created title appears.
        void this.loadConversations(true);
        break;
      }
    }
  }

  // ── Smooth streaming drip (verbatim from menabot-ui) ──

  private startDrip(): void {
    if (this.dripTimerId !== null) return;
    this.dripTimerId = setTimeout(() => this.dripTick(), 0);
  }

  private dripTick(): void {
    this.dripTimerId = null;
    if (!this.contentQueue || !this.dripAssistantId) return;

    const match = this.contentQueue.match(/^\s*\S+\s?/);
    const end = match ? match[0].length : Math.min(1, this.contentQueue.length);
    const chunk = this.contentQueue.slice(0, end);
    this.contentQueue = this.contentQueue.slice(end);

    this.messages.update(msgs =>
      msgs.map(m =>
        m.trackId === this.dripAssistantId
          ? { ...m, content: (m.content ?? '') + chunk }
          : m,
      ),
    );

    if (this.contentQueue) {
      const delay = this.contentQueue.length > 200 ? 0
                  : this.contentQueue.length > 80  ? 8
                  : this.contentQueue.length > 30  ? 16
                  : 22;
      this.dripTimerId = setTimeout(() => this.dripTick(), delay);
    }
  }

  private flushContentQueue(trackId: string): void {
    if (this.dripTimerId !== null) {
      clearTimeout(this.dripTimerId);
      this.dripTimerId = null;
    }
    if (this.contentQueue) {
      const remaining = this.contentQueue;
      this.contentQueue = '';
      this.messages.update(msgs =>
        msgs.map(m =>
          m.trackId === trackId
            ? { ...m, content: (m.content ?? '') + remaining }
            : m,
        ),
      );
    }
    this.dripAssistantId = null;
  }

  // ── Helpers ──

  private setIsAPILoading(isLoading: boolean): void {
    this.pendingApiRequests.update(count => isLoading ? count + 1 : Math.max(0, count - 1));
  }

  private clearMessages(): void {
    this.messages.set([]);
    this.hasMoreMessages.set(false);
  }

  private generateId(): string {
    return `msg_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
  }

  private generateSessionId(): string {
    return `session_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
  }

  private toConversationVM(stored: StoredConversation): ConversationsVM {
    return {
      id: stored.Id,
      title: stored.Title,
      // ConversationType is a free-form string from menabot-ui's backend; default to Web.
      clientType: ChannelType.Web,
      createdAt: stored.CreatedAt,
      modifiedAt: stored.ModifiedAt,
      chatSessionId: stored.ChatSessionId ?? null,
    };
  }

  private async findStoredConversation(chatId: number): Promise<{ ChatSessionId?: string | null; Title: string } | null> {
    // Prefer the cached sidebar list — avoids a round-trip when navigating between threads.
    const cached = this.chatConversations().find(c => c.id === chatId);
    if (cached) {
      return { ChatSessionId: cached.chatSessionId ?? null, Title: cached.title };
    }
    try {
      const res = await firstValueFrom(this.chatService.getConversations(this.userId()));
      const stored = (res?.data ?? []).find(c => c.Id === chatId);
      if (stored) {
        // Refresh the cache so subsequent lookups stay fast.
        this.chatConversations.update(list => {
          if (list.some(c => c.id === stored.Id)) return list;
          return [...list, this.toConversationVM(stored)];
        });
        return { ChatSessionId: stored.ChatSessionId ?? null, Title: stored.Title };
      }
      return null;
    } catch {
      return null;
    }
  }

  private parseSuggestiveActions(actions?: SuggestiveAction[]): SuggestiveAction[] | undefined {
    if (!actions || actions.length === 0) return actions;
    return actions.map(action => {
      let shortTitle = action.short_title ?? '';
      let description = action.description ?? '';
      const reprMatch = shortTitle.match(/^short_title='([^']*)'\s*description='([^']*)'$/);
      if (reprMatch) {
        shortTitle = reprMatch[1];
        description = reprMatch[2];
      }
      return { short_title: shortTitle, description };
    });
  }

  private parseCitations(content: string): Citation[] {
    const citations: Citation[] = [];
    const citationsBlockMatch = content.match(/\n?\s*Citations:\s*\n([\s\S]*)$/i);
    const searchContent = citationsBlockMatch ? citationsBlockMatch[1] : content;

    const linePattern = /^\s*((?:\[\d+\])+):?\s*(.+?)\s*$/gm;
    let lineMatch: RegExpExecArray | null;
    while ((lineMatch = linePattern.exec(searchContent)) !== null) {
      const bracketsPart = lineMatch[1];
      const rawSource = lineMatch[2].replace(/\.+$/, '').trim();
      if (!rawSource) continue;

      const indexes: number[] = [];
      const numPattern = /\[(\d+)\]/g;
      let numMatch: RegExpExecArray | null;
      while ((numMatch = numPattern.exec(bracketsPart)) !== null) {
        indexes.push(parseInt(numMatch[1], 10));
      }

      if (indexes.length > 0) {
        const isUrl = /^https?:\/\//.test(rawSource);
        citations.push({ indexes, source: rawSource, isUrl });
      }
    }
    return citations;
  }
}