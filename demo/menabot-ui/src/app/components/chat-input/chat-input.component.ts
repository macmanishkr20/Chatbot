import { Component, ChangeDetectionStrategy, computed, inject, signal, ElementRef, ViewChild } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ChatService } from '../../services/chat.service';
import { MENA_FUNCTIONS } from '../function-chips/function-chips.component';
import { AgentsMetadataService } from '../../services/agents-metadata.service';

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
  private readonly agentsMeta = inject(AgentsMetadataService);

  inputText = signal('');

  /** Whether to surface the "Build a report" icon — only when an analytical
   *  agent with a report builder schema is the current module. */
  readonly canBuildReport = computed(() => {
    const a = this.agentsMeta.byName(this.chat.selectedAgent());
    return !!a && a.category === 'analytical' && !!a.report_builder;
  });

  openReportPanel(): void {
    this.chat.reportPanelOpen.set(true);
  }

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
