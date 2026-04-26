import { Injectable, inject, signal, computed } from '@angular/core';
import { ApiService } from './api.service';
import { AuthService } from './auth.service';
import {
  ChatMessage,
  Citation,
  Conversation,
  FinalEvent,
  SSEEvent,
  SuggestiveAction,
  ThinkingStep,
} from '../models/chat.models';

/**
 * Central chat state manager using Angular 19 signals.
 *
 * Manages:
 *  - Current conversation messages
 *  - Streaming state (thought steps, content accumulation)
 *  - Conversation list (sidebar)
 *  - Active session tracking
 */
@Injectable({ providedIn: 'root' })
export class ChatService {
  private readonly api = inject(ApiService);
  private readonly auth = inject(AuthService);

  // ── Reactive State (Signals) ──

  /** All messages in the current conversation. */
  readonly messages = signal<ChatMessage[]>([]);

  /** Conversations list for the sidebar. */
  readonly conversations = signal<Conversation[]>([]);

  /** Active conversation ID (null = new chat). */
  readonly activeSessionId = signal<string | null>(null);

  /** Active chat_id from SQL (set after first response). */
  readonly activeChatId = signal<string | number | null>(null);

  /** Conversation title (auto-generated or user-set). */
  readonly conversationTitle = signal<string | null>(null);

  /** Whether a stream is currently active. */
  readonly isStreaming = signal(false);

  /** Whether the sidebar is visible (mobile toggle). */
  readonly sidebarOpen = signal(true);

  /** Current user ID derived from auth. */
  readonly userId = computed(() => this.auth.userEmail() || 'demo.user@gds.ey.com');

  /** Loading state for conversation list. */
  readonly conversationsLoading = signal(false);

  /** Currently selected MENA function code (e.g. 'AWS', 'Talent'). */
  readonly selectedFunction = signal<string | null>(null);

  /** Glow / shimmer the function chips below the input. */
  readonly chipsHighlighted = signal(false);

  /** Optional reason text the backend gave for asking to (re)select. */
  readonly functionPromptReason = signal<string | null>(null);

  /** Query to automatically resend after the user picks a function. */
  private pendingResendQuery: string | null = null;

  /** Error message (null = no error). */
  readonly error = signal<string | null>(null);

  /** Count of user messages (for edit indexing). */
  readonly userMessageCount = computed(() =>
    this.messages().filter(m => m.role === 'user').length
  );

  // ── Internal ──
  private abortController: AbortController | null = null;
  private userMsgCounter = 0;

  // ── Smooth streaming (word-by-word drip buffer) ──
  private contentQueue = '';
  private dripTimerId: ReturnType<typeof setTimeout> | null = null;
  private dripAssistantId: string | null = null;

  // ── Public API ──

  /** Start a new chat — clears messages and generates a new session ID. */
  newChat(): void {
    this.messages.set([]);
    this.activeSessionId.set(this.generateSessionId());
    this.activeChatId.set(null);
    this.conversationTitle.set(null);
    this.error.set(null);
    this.userMsgCounter = 0;
    this.selectedFunction.set(null);
    this.chipsHighlighted.set(true);
    this.functionPromptReason.set(null);
    this.pendingResendQuery = null;
  }

  /** Called by the function-chips component when the user picks a chip. */
  selectFunction(code: string): void {
    this.selectedFunction.set(code);
    this.chipsHighlighted.set(false);
    this.functionPromptReason.set(null);

    const pending = this.pendingResendQuery;
    this.pendingResendQuery = null;
    if (pending && !this.isStreaming()) {
      void this.sendMessage(pending);
    }
  }

  /** Clear the active function (clicking the selected chip / "x" on pill). */
  clearFunction(): void {
    this.selectedFunction.set(null);
    this.pendingResendQuery = null;
  }

  /** Send a user message and stream the response. */
  async sendMessage(text: string): Promise<void> {
    if (this.isStreaming() || !text.trim()) return;

    // Ensure we have a session
    if (!this.activeSessionId()) {
      this.activeSessionId.set(this.generateSessionId());
    }

    const userMsg: ChatMessage = {
      id: this.generateId(),
      role: 'user',
      content: text.trim(),
      userMessageIndex: this.userMsgCounter++,
      timestamp: new Date(),
    };

    this.messages.update(msgs => [...msgs, userMsg]);

    const fn = this.selectedFunction();
    await this.streamResponse({
      input_type: 'ask',
      user_input: text.trim(),
      is_free_form: true,
      user_id: this.userId(),
      chat_session_id: this.activeSessionId(),
      chat_id: this.activeChatId() ? String(this.activeChatId()) : undefined,
      function: fn ? [fn] : [],
      sub_function: [],
      source_url: [],
      start_date: '',
      end_date: '',
      content_type: 'qna_pair',
    });
  }

  /** Edit a user message at the given index and re-run from that point. */
  async editMessage(messageIndex: number, newText: string): Promise<void> {
    if (this.isStreaming() || !newText.trim()) return;

    const msgs = this.messages();
    // Find all user messages
    const userMsgs = msgs.filter(m => m.role === 'user');
    if (messageIndex < 0 || messageIndex >= userMsgs.length) return;

    const editedUserMsg = userMsgs[messageIndex];
    // Find position in full message array
    const editPos = msgs.indexOf(editedUserMsg);
    if (editPos === -1) return;

    // Truncate: keep messages before the edited one, replace it
    const kept = msgs.slice(0, editPos);
    const updatedUserMsg: ChatMessage = {
      ...editedUserMsg,
      content: newText.trim(),
      isEditing: false,
    };
    kept.push(updatedUserMsg);

    this.messages.set(kept);
    this.userMsgCounter = messageIndex + 1;

    const fn = this.selectedFunction();
    await this.streamResponse(undefined, {
      user_id: this.userId(),
      chat_session_id: this.activeSessionId()!,
      message_index: messageIndex,
      new_input: newText.trim(),
      is_free_form: true,
      function: fn ? [fn] : [],
      sub_function: [],
      source_url: [],
      start_date: '',
      end_date: '',
      content_type: 'qna_pair',
    });
  }

  /** Regenerate the last assistant response. */
  async regenerate(): Promise<void> {
    if (this.isStreaming() || !this.activeChatId()) return;

    // Remove the last assistant message
    const msgs = this.messages();
    const lastAssistantIdx = msgs.length - 1;
    if (msgs[lastAssistantIdx]?.role === 'assistant') {
      this.messages.set(msgs.slice(0, lastAssistantIdx));
    }

    await this.streamResponse(undefined, undefined, {
      user_id: this.userId(),
      chat_id: String(this.activeChatId()),
      chat_session_id: this.activeSessionId()!,
    });
  }

  /** Cancel the current in-flight stream. */
  cancelStream(): void {
    this.abortController?.abort();
    // Flush any buffered content before cancelling
    if (this.dripAssistantId) {
      this.flushContentQueue(this.dripAssistantId);
    }
    this.api.cancelChat({
      user_id: this.userId(),
      chat_session_id: this.activeSessionId()!,
    }).subscribe();
    this.isStreaming.set(false);
  }

  /** Load conversation list for sidebar. */
  loadConversations(): void {
    this.conversationsLoading.set(true);
    this.api.getConversations(this.userId()).subscribe({
      next: (res) => {
        this.conversations.set(res.data || []);
        this.conversationsLoading.set(false);
      },
      error: (err) => {
        console.error('Failed to load conversations:', err);
        this.conversationsLoading.set(false);
      },
    });
  }

  /** Load a past conversation's messages. */
  loadConversation(conv: Conversation): void {
    this.activeChatId.set(conv.Id);
    this.conversationTitle.set(conv.Title);
    // Restore the original LangGraph session ID so edit/regenerate find the right
    // checkpoint.  Fall back to String(conv.Id) only for conversations created before
    // the ChatSessionId column was added (legacy rows where it is null).
    this.activeSessionId.set(conv.ChatSessionId || String(conv.Id));
    this.messages.set([]);
    this.userMsgCounter = 0;

    this.api.getMessages(this.userId(), conv.Id).subscribe({
      next: (res) => {
        const msgs: ChatMessage[] = [];
        for (const stored of (res.data || [])) {
          if (stored.UserPrompt) {
            msgs.push({
              id: stored.MessageId || this.generateId(),
              role: 'user',
              content: stored.UserPrompt,
              userMessageIndex: this.userMsgCounter++,
              timestamp: new Date(stored.CreatedAt),
            });
          }
          if (stored.AiContentFreeForm) {
            let content = stored.AiContentFreeForm;
            // AiContentFreeForm may be JSON-encoded string
            try {
              const parsed = JSON.parse(content);
              if (typeof parsed === 'string') content = parsed;
            } catch { /* keep as-is */ }
            msgs.push({
              id: this.generateId(),
              role: 'assistant',
              content,
              messageId: stored.MessageId || undefined,
              citations: this.parseCitations(content),
              timestamp: new Date(stored.CreatedAt),
            });
          }
        }
        this.messages.set(msgs);
      },
      error: (err) => {
        console.error('Failed to load messages:', err);
        this.error.set('Failed to load conversation');
      },
    });
  }

  /** Delete a conversation. */
  deleteConversation(conv: Conversation): void {
    this.api.deleteConversation(this.userId(), conv.Id).subscribe({
      next: () => {
        this.conversations.update(list => list.filter(c => c.Id !== conv.Id));
        // If we deleted the active conversation, start a new one
        if (this.activeChatId() === conv.Id) {
          this.newChat();
        }
      },
      error: (err) => console.error('Failed to delete conversation:', err),
    });
  }

  /** Rename a conversation. */
  renameConversation(conv: Conversation, newTitle: string): void {
    this.api.renameConversation(this.userId(), conv.Id, { title: newTitle }).subscribe({
      next: () => {
        this.conversations.update(list =>
          list.map(c => c.Id === conv.Id ? { ...c, Title: newTitle } : c)
        );
        if (this.activeChatId() === conv.Id) {
          this.conversationTitle.set(newTitle);
        }
      },
      error: (err) => console.error('Failed to rename conversation:', err),
    });
  }

  /** Submit feedback for a message. */
  submitFeedback(messageId: string, rating: number, comments?: string): void {
    this.api.submitFeedback({
      user_id: this.userId(),
      message_id: messageId,
      rating,
      comments,
    }).subscribe({
      error: (err) => console.error('Failed to submit feedback:', err),
    });
  }

  /** Toggle message edit mode. */
  toggleEdit(msgId: string): void {
    this.messages.update(msgs =>
      msgs.map(m => {
        if (m.id === msgId && m.role === 'user') {
          return { ...m, isEditing: !m.isEditing, editText: m.content };
        }
        return { ...m, isEditing: false };
      })
    );
  }

  /** Cancel editing. */
  cancelEdit(msgId: string): void {
    this.messages.update(msgs =>
      msgs.map(m => m.id === msgId ? { ...m, isEditing: false } : m)
    );
  }

  // ── Private: Core streaming logic ──

  private async streamResponse(
    chatBody?: {
      input_type: 'ask';
      user_input: string;
      is_free_form: boolean;
      user_id: string;
      chat_session_id: string | null;
      chat_id?: string;
      function: string[];
      sub_function: string[];
      source_url: string[];
      start_date: string;
      end_date: string;
      content_type?: 'qna_pair' | 'document';
    },
    editBody?: {
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
      content_type?: 'qna_pair' | 'document';
    },
    regenBody?: {
      user_id: string;
      chat_id: string;
      chat_session_id: string;
    },
  ): Promise<void> {
    this.isStreaming.set(true);
    this.error.set(null);
    this.abortController = new AbortController();

    // Create placeholder assistant message
    const assistantMsg: ChatMessage = {
      id: this.generateId(),
      role: 'assistant',
      content: '',
      thinkingSteps: [],
      thinkingCollapsed: false,
      isStreaming: true,
      timestamp: new Date(),
    };
    this.messages.update(msgs => [...msgs, assistantMsg]);

    let activeStepNode: string | null = null;

    try {
      const stream = editBody
        ? this.api.streamEdit(editBody, this.abortController.signal)
        : regenBody
          ? this.api.streamRegenerate(regenBody, this.abortController.signal)
          : this.api.streamChat(chatBody!, this.abortController.signal);

      for await (const event of stream) {
        this.processSSEEvent(event, assistantMsg.id, activeStepNode);
        if (event.type === 'thought') {
          activeStepNode = event.node;
        }
      }
    } catch (err: unknown) {
      if (err instanceof Error && err.name === 'AbortError') {
        // User cancelled — expected
      } else {
        console.error('Stream error:', err);
        this.error.set('Failed to get response. Please try again.');
      }
    } finally {
      // Flush any remaining buffered content immediately
      this.flushContentQueue(assistantMsg.id);

      // Finalize the assistant message
      this.messages.update(msgs =>
        msgs.map(m =>
          m.id === assistantMsg.id
            ? { ...m, isStreaming: false, thinkingCollapsed: true }
            : m
        )
      );
      this.isStreaming.set(false);
      this.abortController = null;
    }
  }

  private processSSEEvent(event: SSEEvent, assistantId: string, activeStepNode: string | null): void {
    switch (event.type) {
      case 'thought': {
        this.messages.update(msgs =>
          msgs.map(m => {
            if (m.id !== assistantId) return m;

            // Mark previous active step as done
            const steps = (m.thinkingSteps ?? []).map(s =>
              s.state === 'running' ? { ...s, state: 'done' as const } : s
            );
            steps.push({ node: event.node, message: event.message, state: 'running' });
            return { ...m, thinkingSteps: steps };
          })
        );
        break;
      }

      case 'content': {
        this.contentQueue += event.content;
        this.dripAssistantId = assistantId;
        this.startDrip();
        break;
      }

      case 'final': {
        const final = event as FinalEvent;
        if (final.cancelled) return;

        if (final.chat_id) this.activeChatId.set(final.chat_id);
        if (final.conversation_title) this.conversationTitle.set(final.conversation_title);

        if (final.requires_function_selection) {
          this.chipsHighlighted.set(true);
          this.functionPromptReason.set(final.function_required_reason ?? null);
          // Stash the user's last query so we can auto-resend after they pick.
          const msgs = this.messages();
          for (let i = msgs.length - 1; i >= 0; i--) {
            if (msgs[i].role === 'user') {
              this.pendingResendQuery = msgs[i].content;
              break;
            }
          }
        } else if (final.selected_function) {
          // Gate auto-selected a function from the query text — reflect it in the chip UI.
          this.selectedFunction.set(final.selected_function);
        }

        // Parse suggestive actions — backend may send Python repr strings
        const parsedActions = this.parseSuggestiveActions(final.suggestive_actions);

        this.messages.update(msgs =>
          msgs.map(m => {
            if (m.id !== assistantId) return m;
            // Mark all remaining steps as done
            const steps = (m.thinkingSteps ?? []).map(s => ({ ...s, state: 'done' as const }));
            // If no content was streamed, use ai_content from final event
            const content = m.content || (typeof final.ai_content === 'string' ? final.ai_content : m.content);
            const citations = this.parseCitations(content);
            return {
              ...m,
              content,
              thinkingSteps: steps,
              chatId: final.chat_id,
              messageId: final.message_id,
              suggestiveActions: parsedActions,
              conversationTitle: final.conversation_title,
              citations,
            };
          })
        );

        // Refresh sidebar
        this.loadConversations();
        break;
      }
    }
  }

  // ── Smooth streaming: word-by-word drip with deliberate pacing ──

  /**
   * Start the drip timer if not already running.
   * Words are revealed one at a time at ~30 words/sec, speeding up
   * when the buffer grows so we never fall far behind the backend.
   * This produces the smooth Gemini-style "materialising" effect.
   */
  private startDrip(): void {
    if (this.dripTimerId !== null) return;
    this.dripTimerId = setTimeout(() => this.dripTick(), 0);
  }

  private dripTick(): void {
    this.dripTimerId = null;
    if (!this.contentQueue || !this.dripAssistantId) return;

    // Extract the next word (including its trailing whitespace)
    const match = this.contentQueue.match(/^\s*\S+\s?/);
    const end = match ? match[0].length : Math.min(1, this.contentQueue.length);
    const chunk = this.contentQueue.slice(0, end);
    this.contentQueue = this.contentQueue.slice(end);

    this.messages.update(msgs =>
      msgs.map(m =>
        m.id === this.dripAssistantId
          ? { ...m, content: m.content + chunk }
          : m
      )
    );

    if (this.contentQueue) {
      // Adaptive pacing: slow when buffer is small (smooth feel),
      // fast when buffer is large (catch up to backend).
      const delay = this.contentQueue.length > 200 ? 50
                  : this.contentQueue.length > 80  ? 65
                  : 85;
      this.dripTimerId = setTimeout(() => this.dripTick(), delay);
    }
  }

  /** Flush all remaining buffered content at once (used when stream ends). */
  private flushContentQueue(assistantId: string): void {
    if (this.dripTimerId !== null) {
      clearTimeout(this.dripTimerId);
      this.dripTimerId = null;
    }
    if (this.contentQueue) {
      const remaining = this.contentQueue;
      this.contentQueue = '';
      this.messages.update(msgs =>
        msgs.map(m =>
          m.id === assistantId
            ? { ...m, content: m.content + remaining }
            : m
        )
      );
    }
    this.dripAssistantId = null;
  }

  // ── Helpers ──

  private generateId(): string {
    return `msg_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
  }

  private generateSessionId(): string {
    return `session_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
  }

  /**
   * Parse suggestive actions from backend.
   * Backend may send Python repr strings like:
   *   { "short_title": "short_title='AWS information' description='What is AWS?'" }
   * We extract the actual short_title and description values.
   */
  private parseSuggestiveActions(actions?: SuggestiveAction[]): SuggestiveAction[] | undefined {
    if (!actions || actions.length === 0) return actions;

    return actions.map(action => {
      let shortTitle = action.short_title ?? '';
      let description = action.description ?? '';

      // Check if short_title contains Python repr format: "short_title='...' description='...'"
      const reprMatch = shortTitle.match(/^short_title='([^']*)'\s*description='([^']*)'$/);
      if (reprMatch) {
        shortTitle = reprMatch[1];
        description = reprMatch[2];
      }

      return { short_title: shortTitle, description };
    });
  }

  /**
   * Extract citations from the response content.
   * Supports both URL-based and document-name-based citations:
   *   [1][2][3] https://...              →  { indexes: [1,2,3], source: "https://...", isUrl: true }
   *   [1] Finance_Internal_QnA_Document. →  { indexes: [1], source: "Finance_Internal_QnA_Document", isUrl: false }
   */
  private parseCitations(content: string): Citation[] {
    const citations: Citation[] = [];

    // First isolate the Citations block if present
    const citationsBlockMatch = content.match(/\n?\s*Citations:\s*\n([\s\S]*)$/i);
    const searchContent = citationsBlockMatch ? citationsBlockMatch[1] : content;

    // Match [number] groups followed by a source (URL or document name)
    const linePattern = /^\s*((?:\[\d+\])+):?\s*(.+?)\s*$/gm;
    let lineMatch: RegExpExecArray | null;

    while ((lineMatch = linePattern.exec(searchContent)) !== null) {
      const bracketsPart = lineMatch[1];
      const rawSource = lineMatch[2].replace(/\.+$/, '').trim(); // strip trailing dots

      if (!rawSource) continue;

      // Extract every [number] from the brackets portion
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
