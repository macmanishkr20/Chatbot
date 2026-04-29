import { CommonModule } from '@angular/common';
import { Component, EventEmitter, inject, Input, OnInit, Output, TemplateRef, ViewChild } from '@angular/core';
import { NgbModal, NgbModalOptions } from '@ng-bootstrap/ng-bootstrap';
import { ChatResponse } from '../../models/chat.model';
import { Role } from '../../models/chat.model';
import { AuthUser } from '../../../../../_shared/messaging-service/auth-user';
import { DomSanitizer, SafeUrl } from '@angular/platform-browser';
import { MessageFeedbackFormComponent } from '../message-feedback-form/message-feedback-form.component';
import { FeedbackRating } from '../../../../../_shared/constants/feedback-rating';
import { FeedbackFormConfig, FeedbackFormData } from '../../models/message-feedabck';
import { SafeMarkdownPipe } from '../../pipes/safe-markdown.pipe';
import { SvgIconComponent } from '../../../../../_shared/components/svg-icon/svg-icon.component';

@Component({
  selector: 'app-chat-message',
  imports: [
    CommonModule,
    MessageFeedbackFormComponent,
    SafeMarkdownPipe,
    SvgIconComponent
  ],
  templateUrl: './chat-message.component.html',
  styleUrl: './chat-message.component.scss',
})
export class ChatMessageComponent implements OnInit {

  @Input() message!: ChatResponse;

  // Show action buttons for which roles?
  @Input() actionsFor: Role[] = ['Assistant'];
  @Input() userAvatarUrl = '';
  @Input() user: AuthUser | null = null;

  // Feedback form configuration
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

  userImage: SafeUrl | string = '';
  private readonly sanitizer = inject(DomSanitizer);
  private readonly modalService = inject(NgbModal);

  feedbackRating: FeedbackRating = FeedbackRating.None;

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
  showActions(m: ChatResponse) {
    return this.actionsFor.includes(m.role) && m.answer?.trim().length > 0 && !m.isStreaming
    && m.conversationId > 0; 
  }

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
      () => this.onFeedbackSkip()
    );
  }

  onFeedbackSubmit(feedbackData: FeedbackFormData) {
    this.feedbackSubmit.emit({
      message: this.message,
      feedback: feedbackData
    });
  }

  onFeedbackSkip() {
    // User skipped - still submit dislike but without comments
    this.feedbackSubmit.emit({
      message: this.message,
      feedback: {
        rating: this.feedbackRating,
        comments: undefined
      }
    });
  }
  // onRegenerate(m: ChatResponse) { 
  //   this.regenerate.emit(m); 
  // }
  onMore(m: ChatResponse) {
    this.more.emit(m);
  }
  // onCopy(m: ChatResponse) { 
  //   this.copy.emit(m); 
  // }

  timestampToDisplay() {
    if (!this.message?.timestamp) {
      return '';
    }
    //If today just time as HH:mm am/pm, else show date as well
    const date = new Date(this.message.timestamp);
    const today = new Date();
    if (date.toDateString() === today.toDateString()) {
      return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    }
    return date.toLocaleString([],
      { hour: '2-digit', minute: '2-digit', day: '2-digit', month: '2-digit', year: 'numeric' });
  }
  getTimeStamp() {
    if (this.isUser()) {
      return this.timestampToDisplay();
    }
    return `MENA CHAT BE ${this.timestampToDisplay()}`;
  }
}
