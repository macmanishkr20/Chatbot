import { Component, ChangeDetectionStrategy, inject, input, output, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ChatMessage, Citation, SuggestiveAction } from '../../models/chat.models';
import { MarkdownPipe } from '../../pipes/markdown.pipe';
import { ThinkingPanelComponent } from '../thinking-panel/thinking-panel.component';
import { DeepSearchPanelComponent } from '../deep-search-panel/deep-search-panel.component';
import { SuggestiveActionsComponent } from '../suggestive-actions/suggestive-actions.component';
import { ChatService } from '../../services/chat.service';
import { ExportService } from '../../services/export.service';
import { AuthService } from '../../services/auth.service';
import { FeedbackModalComponent } from '../feedback-modal/feedback-modal.component';

@Component({
  selector: 'app-message-bubble',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    MarkdownPipe,
    ThinkingPanelComponent,
    DeepSearchPanelComponent,
    SuggestiveActionsComponent,
    FeedbackModalComponent,
  ],
  templateUrl: './message-bubble.component.html',
  styleUrl: './message-bubble.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class MessageBubbleComponent {
  private readonly chat = inject(ChatService);
  readonly exporter = inject(ExportService);
  readonly auth = inject(AuthService);

  /** The message to render. */
  message = input.required<ChatMessage>();

  /** Whether this is the last assistant message (for regenerate). */
  isLastAssistant = input(false);

  /** Emitted when a suggestive action is clicked. */
  actionClicked = output<SuggestiveAction>();

  editText = '';

  readonly citationsExpanded = signal<boolean>(false);

  // Feedback modal state
  readonly showFeedback = signal(false);
  readonly feedbackRating = signal(0);
  readonly feedbackGiven = signal<'up' | 'down' | null>(null);

  // ── Computed getters ──

  /**
   * Clean the content for display:
   *  - Strip any embedded JSON metadata objects
   *  - Strip the entire "Citations:" block (header + ref/URL lines)
   *  - Strip any remaining standalone citation definition lines
   */
  get displayContent(): string {
    let raw = this.message().content;

    // Strip [NO_ANSWER] prefix — the LLM uses this as an internal signal
    // that the retrieved documents don't cover the query. It must never
    // be shown to the user (handled fully on the final event, but also
    // stripped here to prevent it flashing during token-by-token streaming).
    raw = raw.replace(/^\s*\[NO_ANSWER\]\s*/i, '');

    // Strip embedded JSON objects
    raw = raw.replace(/\{[\s\S]*?\}/g, (match) => {
      try {
        JSON.parse(match);
        return '';
      } catch {
        return match;
      }
    });

    // Strip the entire "Citations:" block and everything after it
    raw = raw.replace(/\n?\s*Citations:\s*[\s\S]*$/i, '');

    // Strip citation definition lines: [1] https://... or [1] Document_Name
    raw = raw.replace(/^\s*(?:\[\d+\])+:?\s*\S.*$/gm, '');

    // Strip standalone bracket reference lines: [1][2][3]
    raw = raw.replace(/^\s*(?:\[\d+\])+\s*$/gm, '');

    return raw.trim();
  }

  get citations(): Citation[] {
    return this.message().citations || [];
  }

  get hasCitations(): boolean {
    return this.citations.length > 0;
  }

  get isBot(): boolean {
    return this.message().role === 'assistant';
  }

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

  exportAsWord(): void {
    this.exporter.exportMessage('docx', this.message().content);
  }

  exportAsExcel(): void {
    this.exporter.exportMessage('xlsx', this.message().content);
  }

  thumbsUp(): void {
    if (this.feedbackGiven()) return;
    this.feedbackRating.set(1);
    this.showFeedback.set(true);
  }

  thumbsDown(): void {
    if (this.feedbackGiven()) return;
    this.feedbackRating.set(-1);
    this.showFeedback.set(true);
  }

  onFeedbackSubmitted(): void {
    this.feedbackGiven.set(this.feedbackRating() >= 1 ? 'up' : 'down');
    this.showFeedback.set(false);
  }

  onFeedbackClosed(): void {
    this.showFeedback.set(false);
  }

  toggleCitations(): void {
    this.citationsExpanded.update(v => !v);
  }
}
