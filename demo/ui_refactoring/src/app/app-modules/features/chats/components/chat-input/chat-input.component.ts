import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, ElementRef, EventEmitter, inject, Input, Output, ViewChild, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { ChatQueryDTO } from '../../models/chat.model';
import { ChatStore } from '../../services/chat.store';
import { SvgIconComponent } from '../../../../../_shared/components/svg-icon/svg-icon.component';
import { FunctionChipsComponent, MENA_FUNCTIONS } from '../function-chips/function-chips.component';

/**
 * Chat composer.
 *
 * Drives `ChatStore.sendMessage()` directly (matching menabot-ui's chat-input
 * behaviour). Stop / cancel button replaces the send button while a stream
 * is active. The `send` output remains for any legacy parent that still
 * binds to it, but `ChatStore` is now the single source of truth.
 */
@Component({
  selector: 'app-chat-input',
  imports: [
    CommonModule,
    ReactiveFormsModule,
    SvgIconComponent,
    FunctionChipsComponent,
  ],
  templateUrl: './chat-input.component.html',
  styleUrls: ['./chat-input.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ChatInputComponent {
  readonly chat = inject(ChatStore);
  private formBuilder = inject(FormBuilder);

  @ViewChild('msg') textareaRef!: ElementRef<HTMLTextAreaElement>;

  @Input() placeholder = 'Ask me anything on MENA...';
  @Input() disabled = false;
  @Input() ariaLabel = 'Chat message input';
  @Input() enterToSend = true;
  @Input() shiftToNewLine = true;
  @Input() maxHeightPx = 160;
  @Input() maxLength?: number;
  /** Show MENA function chips below the input. Default true to mirror menabot-ui. */
  @Input() showFunctionChips = true;

  /** Kept for backwards compatibility — chat-container previously listened to this. */
  @Output() send = new EventEmitter<ChatQueryDTO>();
  @Output() attach = new EventEmitter<void>();

  userQueryForm = this.formBuilder.group({
    message: ['', [Validators.required]],
  });

  /** Currently selected MENA function metadata (drives placeholder + pill). */
  readonly selectedChip = computed(() => {
    const code = this.chat.selectedFunction();
    return code ? MENA_FUNCTIONS.find(c => c.code === code) ?? null : null;
  });

  readonly effectivePlaceholder = computed(() => {
    const chip = this.selectedChip();
    return chip ? `Ask about ${chip.full}…` : (this.placeholder || 'Ask me anything on MENA...');
  });

  /** Stream state. */
  readonly isStreaming = this.chat.isStreaming;

  get form() {
    return this.userQueryForm.controls;
  }

  get message(): string {
    return this.userQueryForm.get('message')?.value || '';
  }

  autoResize(el: HTMLTextAreaElement) {
    el.style.height = 'auto';
    const newHeight = Math.min(Math.max(el.scrollHeight, 24), this.maxHeightPx);
    el.style.height = newHeight + 'px';
  }

  onKeyDown(event: KeyboardEvent) {
    if (this.enterToSend && event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      this.onSend();
    }
  }

  onAttach() {
    this.attach.emit();
  }

  onSend() {
    if (this.disabled || this.isStreaming()) return;

    const userMessage = this.message?.trim();
    if (!userMessage) return;

    const chatMessage: ChatQueryDTO = {
      threadId: 1,
      queryId: Date.now().toString(),
      userQuery: userMessage,
    };
    this.send.emit(chatMessage);
    void this.chat.sendMessage(userMessage);

    this.userQueryForm.reset();
    if (this.textareaRef?.nativeElement) {
      this.textareaRef.nativeElement.style.height = 'auto';
    }
  }

  onCancel() {
    this.chat.cancelStream();
  }

  clearFunction() {
    this.chat.clearFunction();
  }
}