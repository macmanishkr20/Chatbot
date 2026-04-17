import {
  Component,
  ChangeDetectionStrategy,
  inject,
  computed,
  ElementRef,
  ViewChild,
  AfterViewInit,
  effect,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { ChatService } from '../../services/chat.service';
import { MessageBubbleComponent } from '../message-bubble/message-bubble.component';
import { ChatInputComponent } from '../chat-input/chat-input.component';
import { SuggestiveAction } from '../../models/chat.models';

@Component({
  selector: 'app-chat-window',
  standalone: true,
  imports: [CommonModule, MessageBubbleComponent, ChatInputComponent],
  templateUrl: './chat-window.component.html',
  styleUrl: './chat-window.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ChatWindowComponent implements AfterViewInit {
  readonly chat = inject(ChatService);

  @ViewChild('scrollContainer') scrollContainer!: ElementRef<HTMLDivElement>;

  /** Derive the title to show in the header. */
  readonly headerTitle = computed(() =>
    this.chat.conversationTitle() || 'New Conversation'
  );

  /** Find the last assistant message index for regenerate button. */
  readonly lastAssistantIdx = computed(() => {
    const msgs = this.chat.messages();
    for (let i = msgs.length - 1; i >= 0; i--) {
      if (msgs[i].role === 'assistant') return i;
    }
    return -1;
  });

  /** Whether to show the empty state (no messages). */
  readonly showEmpty = computed(() => this.chat.messages().length === 0);

  constructor() {
    // Auto-scroll when messages change
    effect(() => {
      this.chat.messages(); // track dependency
      this.scrollToBottom();
    });
  }

  ngAfterViewInit(): void {
    this.scrollToBottom();
  }

  toggleSidebar(): void {
    this.chat.sidebarOpen.update(v => !v);
  }

  onActionClicked(action: SuggestiveAction): void {
    this.chat.sendMessage(action.short_title);
  }

  trackById(_: number, msg: { id: string }): string {
    return msg.id;
  }

  private scrollToBottom(): void {
    setTimeout(() => {
      const el = this.scrollContainer?.nativeElement;
      if (el) {
        el.scrollTop = el.scrollHeight;
      }
    }, 50);
  }
}
