import { Component, computed, effect, inject, OnInit, OnDestroy, ViewChild, ElementRef } from '@angular/core';
import { ChatMessageComponent } from '../chat-message/chat-message.component';
import { ChatResponse, SuggestiveAction } from '../../models/chat.model';
import { ChatStore } from '../../services/chat.store';
import { CommonModule } from '@angular/common';
import { FeedbackRating } from '../../../../../_shared/constants/feedback-rating';
import { ToastService } from '../../../../../_shared/toast-global/toast.service';
import { FeedbackDTO, FeedbackFormConfig, FeedbackFormData } from '../../models/message-feedabck';
import { ActivatedRoute } from '@angular/router';
import { Subject, takeUntil } from 'rxjs';
import { FeedbackTag } from '../../../../../_shared/constants/feedback-tag';

@Component({
  selector: 'app-chat-window',
  imports: [
    ChatMessageComponent,
    CommonModule,
  ],
  templateUrl: './chat-window.component.html',
  styleUrl: './chat-window.component.scss',
})
export class ChatWindowComponent implements OnInit, OnDestroy {
  @ViewChild('messagesContainer') private messagesContainer!: ElementRef<HTMLElement>;

  chatStore = inject(ChatStore);
  private toastService = inject(ToastService);
  private route = inject(ActivatedRoute);
  private destroy$ = new Subject<void>();
  loadingOlderMessages = false;
  private userScrolledUp = false;
  private pendingScrollToLastUser = false;

  /** Index of the last assistant message — drives the regenerate button. */
  readonly lastAssistantIdx = computed(() => {
    const msgs = this.chatStore.messages();
    for (let i = msgs.length - 1; i >= 0; i--) {
      if (msgs[i].role === 'Assistant') return i;
    }
    return -1;
  });

  // Reactive feedback form config — serviceHierarchies from store, loaded once
  readonly feedbackFormConfig = computed<FeedbackFormConfig>(() => ({
    showComments: true,
    showTags: true,
    tags: [FeedbackTag.UserExperience, FeedbackTag.ContentGaps, FeedbackTag.Other],
    showCategory: false,
    showServiceHierarchy: true,
    serviceHierarchies: this.chatStore.serviceHierarchies(),
    commentsRequired: false,
    commentsPlaceholder: 'Please tell us what went wrong or how we can improve...',
    commentsMaxLength: 500,
  }));

  constructor() {
    effect(() => {
      const feedBackResult = this.chatStore.feedbackResult();
      if (feedBackResult) {
        this.toastService.show(feedBackResult.message, {
          classname: feedBackResult.success ? 'bg-success text-light' : 'bg-danger text-light',
          autohide: true,
          delay: 3000,
        });
        this.chatStore.clearFeedbackResult();
      }
    });

    effect(() => {
      this.chatStore.selectedConversationId();
      this.userScrolledUp = false;
    });

    effect(() => {
      const messages = this.chatStore.messages();
      const loading = this.chatStore.loading();
      const isStreaming = messages.some(m => m.isStreaming);

      if (loading && !isStreaming) {
        this.userScrolledUp = false;
        this.pendingScrollToLastUser = false;
      }

      if (this.pendingScrollToLastUser && !loading && messages.length > 0) {
        this.pendingScrollToLastUser = false;
        this.userScrolledUp = true;
        requestAnimationFrame(() => this.scrollToLastUserMessage());
        return;
      }

      // Always scroll to bottom during streaming or if user hasn't scrolled up
      if (isStreaming || !this.userScrolledUp) {
        requestAnimationFrame(() => this.scrollToBottom());
      }
    });
  }

  ngOnInit(): void {
    void this.chatStore.loadServiceHierarchies();
    this.route.paramMap.pipe(takeUntil(this.destroy$)).subscribe(async paramMap => {
      const id = paramMap.get('id');

      if (!id) {
        this.pendingScrollToLastUser = false;
        if (this.chatStore.selectedConversationId() !== null) {
          this.chatStore.startNewConversation();
        }
      } else {
        const numericId = Number(id);
        if (!isNaN(numericId)) {
          this.pendingScrollToLastUser = true;
          await this.chatStore.loadConversation(numericId);
        }
      }
    });
  }

  ngOnDestroy(): void {
    this.destroy$.next();
    this.destroy$.complete();
  }

  async onMessageScroll(event: Event) {
    const target = event.target as HTMLElement | null;
    if (!target) return;

    const atBottom = target.scrollTop + target.clientHeight >= target.scrollHeight - 150;
    this.userScrolledUp = !atBottom;

    const nearTop = target.scrollTop <= 80;
    if (!nearTop || this.loadingOlderMessages
      || !this.chatStore.hasMoreMessages() || this.chatStore.isAPILoading()) {
      return;
    }

    const previousScrollHeight = target.scrollHeight;
    const previousScrollTop = target.scrollTop;

    this.loadingOlderMessages = true;
    try {
      await this.chatStore.loadMoreMessages();
      requestAnimationFrame(() => {
        const heightDelta = target.scrollHeight - previousScrollHeight;
        if (heightDelta > 0) {
          target.scrollTop = previousScrollTop + heightDelta;
        }
      });
    } finally {
      this.loadingOlderMessages = false;
    }
  }

  private scrollToBottom(): void {
    const el = this.messagesContainer?.nativeElement;
    if (el) {
      el.scrollTop = el.scrollHeight;
    }
  }

  private scrollToLastUserMessage(): void {
    const el = this.messagesContainer?.nativeElement;
    if (!el) return;
    const userMessages = el.querySelectorAll<HTMLElement>('[data-role="User"]');
    if (userMessages.length > 0) {
      userMessages[userMessages.length - 1].scrollIntoView({ behavior: 'instant', block: 'start' });
    } else {
      el.scrollTop = el.scrollHeight;
    }
  }

  async loadMoreMessages() {
    if (this.loadingOlderMessages
      || !this.chatStore.hasMoreMessages() || this.chatStore.isAPILoading()) {
      return;
    }
    this.loadingOlderMessages = true;
    try {
      await this.chatStore.loadMoreMessages();
    } finally {
      this.loadingOlderMessages = false;
    }
  }

  async onLike(m: ChatResponse) {
    const feedback = {
      messageId: m.messageId,
      rating: FeedbackRating.Positive,
    } as FeedbackDTO;
    await this.chatStore.postFeedback(feedback);
  }

  async onFeedbackSubmit(event: { message: ChatResponse, feedback: FeedbackFormData }) {
    const { message, feedback } = event;
    const feedbackToSubmit = {
      messageId: message.messageId,
      rating: feedback.rating,
      comments: feedback.comments,
      functionId: feedback.functionId,
      subFunctionId: feedback.subFunctionId,
      serviceId: feedback.serviceId,
      category: feedback.category,
    } as FeedbackDTO;

    await this.chatStore.postFeedback(feedbackToSubmit);
  }

  /** Wire suggestive-action click → resend the question text. */
  onSuggestiveAction(action: SuggestiveAction): void {
    void this.chatStore.sendMessage(action.short_title);
  }

  /** Wire regenerate button → ChatStore.regenerate(). */
  onRegen(_m: ChatResponse) {
    void this.chatStore.regenerate();
  }

  /** Wire user-message edit → ChatStore.editMessage(index, newText). */
  onEdit(payload: { message: ChatResponse, newText: string }) {
    if (payload.message.userMessageIndex == null) return;
    void this.chatStore.editMessage(payload.message.userMessageIndex, payload.newText);
  }

  /** Toggle inline edit mode for a user message. */
  onToggleEdit(m: ChatResponse) {
    this.chatStore.toggleEdit(m.messageId);
  }

  /** Cancel edit. */
  onCancelEdit(m: ChatResponse) {
    this.chatStore.cancelEdit(m.messageId);
  }

  onMore(m: ChatResponse) {
    console.log('More actions for message', m);
  }

  onCopy(m: ChatResponse) {
    console.log('Copied message', m);
  }
}