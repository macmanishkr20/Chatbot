import { Component, ChangeDetectionStrategy, inject, input, output } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ChatMessage, SuggestiveAction } from '../../models/chat.models';
import { MarkdownPipe } from '../../pipes/markdown.pipe';
import { ThinkingPanelComponent } from '../thinking-panel/thinking-panel.component';
import { SuggestiveActionsComponent } from '../suggestive-actions/suggestive-actions.component';
import { ChatService } from '../../services/chat.service';

@Component({
  selector: 'app-message-bubble',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    MarkdownPipe,
    ThinkingPanelComponent,
    SuggestiveActionsComponent,
  ],
  templateUrl: './message-bubble.component.html',
  styleUrl: './message-bubble.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class MessageBubbleComponent {
  private readonly chat = inject(ChatService);

  /** The message to render. */
  message = input.required<ChatMessage>();

  /** Whether this is the last assistant message (for regenerate). */
  isLastAssistant = input(false);

  /** Emitted when a suggestive action is clicked. */
  actionClicked = output<SuggestiveAction>();

  editText = '';

  // ── User actions ──

  startEdit(): void {
    this.editText = this.message().content;
    this.chat.toggleEdit(this.message().id);
  }

  cancelEdit(): void {
    this.chat.cancelEdit(this.message().id);
  }

  submitEdit(): void {
    const idx = this.message().userMessageIndex;
    if (idx !== undefined && this.editText.trim()) {
      this.chat.editMessage(idx, this.editText);
    }
  }

  regenerate(): void {
    this.chat.regenerate();
  }

  copyContent(): void {
    navigator.clipboard.writeText(this.message().content);
  }

  thumbsUp(): void {
    const msgId = this.message().messageId;
    if (msgId) {
      this.chat.submitFeedback(msgId, 1);
    }
  }

  thumbsDown(): void {
    const msgId = this.message().messageId;
    if (msgId) {
      this.chat.submitFeedback(msgId, -1);
    }
  }
}
