import { Component, ChangeDetectionStrategy, inject, input, output, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ApiService } from '../../services/api.service';
import { AuthService } from '../../services/auth.service';

@Component({
  selector: 'app-feedback-modal',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './feedback-modal.component.html',
  styleUrl: './feedback-modal.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class FeedbackModalComponent {
  private readonly api = inject(ApiService);
  private readonly auth = inject(AuthService);

  messageId = input.required<string>();
  rating = input<number>(1);

  closed = output<void>();
  submitted = output<void>();

  comments = signal('');
  isSubmitting = signal(false);
  submitError = signal('');

  get title(): string {
    return this.rating() >= 1 ? 'What did you like?' : 'What could be improved?';
  }

  submit(): void {
    this.isSubmitting.set(true);
    this.submitError.set('');

    const email = this.auth.userEmail();
    this.api.submitFeedback({
      user_id: email,
      message_id: this.messageId(),
      rating: this.rating(),
      comments: this.comments().trim() || undefined,
      created_by: email,
      modified_by: email,
    }).subscribe({
      next: () => {
        this.isSubmitting.set(false);
        this.submitted.emit();
      },
      error: () => {
        this.isSubmitting.set(false);
        this.submitError.set('Failed to submit feedback. Please try again.');
      },
    });
  }

  cancel(): void {
    this.closed.emit();
  }

  onOverlayClick(event: MouseEvent): void {
    if ((event.target as HTMLElement).classList.contains('modal-overlay')) {
      this.closed.emit();
    }
  }
}
