import { Component, ChangeDetectionStrategy, computed, inject, signal, ElementRef, ViewChild } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ChatService } from '../../services/chat.service';
import { MENA_FUNCTIONS } from '../function-chips/function-chips.component';

@Component({
  selector: 'app-chat-input',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './chat-input.component.html',
  styleUrl: './chat-input.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ChatInputComponent {
  readonly chat = inject(ChatService);

  inputText = signal('');

  /** Currently selected MENA function metadata (for the pill + placeholder). */
  readonly selectedChip = computed(() => {
    const code = this.chat.selectedFunction();
    return code ? MENA_FUNCTIONS.find(c => c.code === code) ?? null : null;
  });

  readonly placeholder = computed(() => {
    const chip = this.selectedChip();
    return chip ? `Ask about ${chip.full}…` : 'Ask me anything...';
  });

  clearFunction(): void {
    this.chat.clearFunction();
  }

  @ViewChild('textareaEl') textareaEl!: ElementRef<HTMLTextAreaElement>;

  send(): void {
    const text = this.inputText().trim();
    if (!text || this.chat.isStreaming()) return;
    this.chat.sendMessage(text);
    this.inputText.set('');
    this.resetHeight();
  }

  onKeydown(event: KeyboardEvent): void {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      this.send();
    }
  }

  cancelStream(): void {
    this.chat.cancelStream();
  }

  autoGrow(event: Event): void {
    const el = event.target as HTMLTextAreaElement;
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 200) + 'px';
  }

  private resetHeight(): void {
    if (this.textareaEl?.nativeElement) {
      this.textareaEl.nativeElement.style.height = 'auto';
    }
  }
}
