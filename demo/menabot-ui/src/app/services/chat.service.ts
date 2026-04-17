import { Injectable, inject, signal, computed } from '@angular/core';
import { ApiService } from './api.service';
import {
  ChatMessage,
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

  /** Current user ID. */
  readonly userId = signal('demo.user@gds.ey.com');

  /** Loading state for conversation list. */
  readonly conversationsLoading = signal(false);

  /** Error message (null = no error). */
  readonly error = signal<string | null>(null);

  /** Count of user messages (for edit indexing). */
  readonly userMessageCount = computed(() =>
    this.messages().filter(m => m.role === 'user').length
  );

  // ── Internal ──
  private abortController: AbortController | null = null;
  private userMsgCounter = 0;

  // ── Public API ──

  /** Start a new chat — clears messages and generates a new session ID. */
  newChat(): void {
    this.messages.set([]);
    this.activeSessionId.set(this.generateSessionId());
    this.activeChatId.set(null);
    this.conversationTitle.set(null);
    this.error.set(null);
    this.userMsgCounter = 0;
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

    await this.streamResponse({
      input_type: 'ask',
      user_input: text.trim(),
      is_free_form: true,
      user_id: this.userId(),
      chat_session_id: this.activeSessionId(),
      function: [],
      sub_function: [],
      source_url: [],
      start_date: '',
      end_date: '',
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

    await this.streamResponse(undefined, {
      user_id: this.userId(),
      chat_session_id: this.activeSessionId()!,
      message_index: messageIndex,
      new_input: newText.trim(),
      is_free_form: true,
      function: [],
      sub_function: [],
      source_url: [],
      start_date: '',
      end_date: '',
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
    this.activeSessionId.set(String(conv.Id));
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
      function: string[];
      sub_function: string[];
      source_url: string[];
      start_date: string;
      end_date: string;
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
        this.messages.update(msgs =>
          msgs.map(m =>
            m.id === assistantId
              ? { ...m, content: m.content + event.content }
              : m
          )
        );
        break;
      }

      case 'final': {
        const final = event as FinalEvent;
        if (final.cancelled) return;

        if (final.chat_id) this.activeChatId.set(final.chat_id);
        if (final.conversation_title) this.conversationTitle.set(final.conversation_title);

        this.messages.update(msgs =>
          msgs.map(m => {
            if (m.id !== assistantId) return m;
            // Mark all remaining steps as done
            const steps = (m.thinkingSteps ?? []).map(s => ({ ...s, state: 'done' as const }));
            return {
              ...m,
              thinkingSteps: steps,
              chatId: final.chat_id,
              messageId: final.message_id,
              suggestiveActions: final.suggestive_actions,
              conversationTitle: final.conversation_title,
            };
          })
        );

        // Refresh sidebar
        this.loadConversations();
        break;
      }
    }
  }

  // ── Helpers ──

  private generateId(): string {
    return `msg_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
  }

  private generateSessionId(): string {
    return `session_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
  }
}
