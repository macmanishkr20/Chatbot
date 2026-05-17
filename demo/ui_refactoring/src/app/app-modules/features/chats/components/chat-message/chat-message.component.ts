import { CommonModule } from '@angular/common';
import { Component, EventEmitter, inject, Input, OnInit, Output, signal, TemplateRef, ViewChild } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { NgbModal, NgbModalOptions } from '@ng-bootstrap/ng-bootstrap';
import { ChatResponse, Citation, SuggestiveAction } from '../../models/chat.model';
import { Role } from '../../models/chat.model';
import { AuthUser } from '../../../../../_shared/messaging-service/auth-user';
import { DomSanitizer, SafeUrl } from '@angular/platform-browser';
import { MessageFeedbackFormComponent } from '../message-feedback-form/message-feedback-form.component';
import { FeedbackRating } from '../../../../../_shared/constants/feedback-rating';
import { FeedbackFormConfig, FeedbackFormData } from '../../models/message-feedabck';
import { SafeMarkdownPipe } from '../../pipes/safe-markdown.pipe';
import { SvgIconComponent } from '../../../../../_shared/components/svg-icon/svg-icon.component';
import { ThinkingPanelComponent } from '../thinking-panel/thinking-panel.component';
import { DeepSearchPanelComponent } from '../deep-search-panel/deep-search-panel.component';
import { SuggestiveActionsComponent } from '../suggestive-actions/suggestive-actions.component';

@Component({
  selector: 'app-chat-message',
  imports: [
    CommonModule,
    FormsModule,
    MessageFeedbackFormComponent,
    SafeMarkdownPipe,
    SvgIconComponent,
    ThinkingPanelComponent,
    DeepSearchPanelComponent,
    SuggestiveActionsComponent,
  ],
  templateUrl: './chat-message.component.html',
  styleUrl: './chat-message.component.scss',
})
export class ChatMessageComponent implements OnInit {

  @Input() message!: ChatResponse;
  @Input() actionsFor: Role[] = ['Assistant'];
  @Input() userAvatarUrl = '';
  @Input() user: AuthUser | null = null;
  /** Whether this is the last assistant message — drives the regenerate button. */
  @Input() isLastAssistant = false;

  @Input() feedbackConfig: FeedbackFormConfig = {
    showComments: true,
    showTags: false,
    showCategory: false,
    commentsPlaceholder: 'Please tell us what went wrong or how we can improve...',
    commentsMaxLength: 500,
    commentsRequired: true,
  };

  @Output() like = new EventEmitter<ChatResponse>();
  @Output() regenerate = new EventEmitter<ChatResponse>();
  @Output() more = new EventEmitter<ChatResponse>();
  @Output() copy = new EventEmitter<ChatResponse>();
  @Output() feedbackSubmit = new EventEmitter<{ message: ChatResponse, feedback: FeedbackFormData }>();
  /** Inline edit flow events. */
  @Output() toggleEdit = new EventEmitter<ChatResponse>();
  @Output() cancelEdit = new EventEmitter<ChatResponse>();
  @Output() submitEdit = new EventEmitter<{ message: ChatResponse, newText: string }>();
  /** Suggestive action click. */
  @Output() suggestiveAction = new EventEmitter<SuggestiveAction>();

  userImage: SafeUrl | string = '';
  private readonly sanitizer = inject(DomSanitizer);
  private readonly modalService = inject(NgbModal);

  feedbackRating: FeedbackRating = FeedbackRating.None;

  /** Local edit text buffer (driven by the user message bubble). */
  editBuffer = '';

  /** Copy tooltip visibility. */
  showCopyTooltip = false;

  readonly citationsExpanded = signal<boolean>(false);

  @ViewChild('feedbackModalTpl', { static: true }) feedbackModalTpl!: TemplateRef<unknown>;

  ngOnInit(): void {
    this.userImage = this.userAvatarToShow();
  }
  userAvatarToShow() {
    if (this.userAvatarUrl) {
      return this.userAvatarUrl;
    }
    return this.sanitizer.bypassSecurityTrustUrl(this.user?.avatarUrl || '');
  }
  get userInitials(): string {
    return this.user?.fullName
      ? this.user.fullName.split(' ').map(n => n[0]).join('')
      : '';
  }

  isUser() {
    return this.message.role === 'User';
  }

  /** Whether the streaming cursor should show — only true if actively streaming content. */
  get showStreamingCursor(): boolean {
    if (!this.message.isStreaming) return false;
    // If thinking steps are all done and we have content, streaming is visually complete
    const steps = this.message.thinkingSteps;
    if (steps && steps.length > 0 && steps.every(s => s.state === 'done') && (this.message.content ?? this.message.answer)) {
      return false;
    }
    return true;
  }

  showActions(m: ChatResponse) {
    return this.actionsFor.includes(m.role) && (m.answer ?? m.content ?? '').trim().length > 0
      && !this.showStreamingCursor;
  }

  // ── Citations (assistant) ──

  get citations(): Citation[] {
    return this.message.citations || [];
  }

  get hasCitations(): boolean {
    return this.citations.length > 0;
  }

  toggleCitations(): void {
    this.citationsExpanded.update(v => !v);
  }

  /**
   * Clean the assistant content for display:
   *  - strip [NO_ANSWER] prefix
   *  - strip embedded JSON metadata blocks
   *  - strip the entire "Citations:" block
   *  - strip standalone bracket reference lines
   */
  get displayContent(): string {
    let raw = this.message.content ?? this.message.answer ?? '';

    raw = raw.replace(/^\s*\[NO_ANSWER\]\s*/i, '');

    raw = raw.replace(/\{[\s\S]*?\}/g, (match) => {
      try {
        JSON.parse(match);
        return '';
      } catch {
        return match;
      }
    });

    raw = raw.replace(/\n?\s*Citations:\s*[\s\S]*$/i, '');
    raw = raw.replace(/^\s*(?:\[\d+\])+:?\s*\S.*$/gm, '');
    raw = raw.replace(/^\s*(?:\[\d+\])+\s*$/gm, '');

    return raw.trim();
  }

  // ── Like / Dislike ──

  onLike(m: ChatResponse) {
    this.like.emit(m);
  }

  onDislike() {
    this.feedbackRating = FeedbackRating.Negative;
    this.openFeedbackModal();
  }

  private openFeedbackModal(): void {
    const options: NgbModalOptions = {
      centered: true,
      backdrop: 'static',
      keyboard: true,
      size: 'md',
      windowClass: 'feedback-modal-window',
    };
    const ref = this.modalService.open(this.feedbackModalTpl, options);

    ref.result.then(
      (data: FeedbackFormData) => this.onFeedbackSubmit(data),
      () => this.onFeedbackSkip(),
    );
  }

  onFeedbackSubmit(feedbackData: FeedbackFormData) {
    this.feedbackSubmit.emit({
      message: this.message,
      feedback: feedbackData,
    });
  }

  onFeedbackSkip() {
    this.feedbackSubmit.emit({
      message: this.message,
      feedback: {
        rating: this.feedbackRating,
        comments: undefined,
      },
    });
  }

  // ── Inline edit (user message) ──

  startEdit() {
    this.editBuffer = this.message.content ?? this.message.answer ?? '';
    this.toggleEdit.emit(this.message);
  }

  doCancelEdit() {
    this.cancelEdit.emit(this.message);
  }

  doSubmitEdit() {
    const newText = (this.editBuffer ?? '').trim();
    if (!newText) return;
    this.submitEdit.emit({ message: this.message, newText });
  }

  // ── Regenerate / copy / suggestive ──

  onRegenerate() {
    this.regenerate.emit(this.message);
  }

  copyContent() {
    const text = this.message.content ?? this.message.answer ?? '';
    navigator.clipboard.writeText(text);
    this.showCopyTooltip = true;
    setTimeout(() => (this.showCopyTooltip = false), 2000);
    this.copy.emit(this.message);
  }

  onSuggestiveAction(action: SuggestiveAction) {
    this.suggestiveAction.emit(action);
  }

  onMore(m: ChatResponse) {
    this.more.emit(m);
  }

  timestampToDisplay() {
    if (!this.message?.timestamp) {
      return '';
    }
    const date = new Date(this.message.timestamp);
    const today = new Date();
    if (date.toDateString() === today.toDateString()) {
      return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    }
    return date.toLocaleString([], { hour: '2-digit', minute: '2-digit', day: '2-digit', month: '2-digit', year: 'numeric' });
  }
  getTimeStamp() {
    if (this.isUser()) {
      return this.timestampToDisplay();
    }
    return `MENA CHAT BE ${this.timestampToDisplay()}`;
  }
}