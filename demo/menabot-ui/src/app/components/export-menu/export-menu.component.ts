import { Component, ChangeDetectionStrategy, inject, signal, computed, HostListener, ElementRef } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ExportService } from '../../services/export.service';
import { ChatService } from '../../services/chat.service';
import { ExportFormat } from '../../models/chat.models';

type FormatChoice = 'docx' | 'xlsx' | 'pptx';

@Component({
  selector: 'app-export-menu',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './export-menu.component.html',
  styleUrl: './export-menu.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ExportMenuComponent {
  readonly exporter = inject(ExportService);
  private readonly chat = inject(ChatService);
  private readonly host = inject(ElementRef<HTMLElement>);

  readonly menuOpen = signal(false);
  readonly modalOpen = signal(false);
  readonly selectedFormat = signal<FormatChoice | null>(null);
  readonly templateFile = signal<File | null>(null);
  readonly formError = signal<string | null>(null);

  readonly hasMessages = computed(() => this.chat.messages().length > 0);

  readonly templateRequired = computed(
    () => this.selectedFormat() === 'pptx',
  );

  readonly modalTitle = computed(() => {
    const f = this.selectedFormat();
    if (f === 'pptx') return 'Export conversation as PowerPoint';
    if (f === 'xlsx') return 'Export conversation as Excel';
    if (f === 'docx') return 'Export conversation as Word';
    return 'Export conversation';
  });

  readonly canSubmit = computed(() => {
    if (this.exporter.busy()) return false;
    if (this.templateRequired() && !this.templateFile()) return false;
    return !!this.selectedFormat();
  });

  toggleMenu(): void {
    this.menuOpen.update(v => !v);
  }

  closeMenu(): void {
    this.menuOpen.set(false);
  }

  @HostListener('document:click', ['$event'])
  onDocumentClick(event: MouseEvent): void {
    if (!this.menuOpen()) return;
    if (!this.host.nativeElement.contains(event.target as Node)) {
      this.menuOpen.set(false);
    }
  }

  pick(format: FormatChoice): void {
    this.menuOpen.set(false);
    this.selectedFormat.set(format);
    this.templateFile.set(null);
    this.formError.set(null);
    this.modalOpen.set(true);
  }

  onTemplateChosen(event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files && input.files[0] ? input.files[0] : null;
    this.templateFile.set(file);
    this.formError.set(null);
  }

  clearTemplate(): void {
    this.templateFile.set(null);
  }

  closeModal(): void {
    if (this.exporter.busy()) return;
    this.modalOpen.set(false);
    this.selectedFormat.set(null);
    this.templateFile.set(null);
    this.formError.set(null);
  }

  onOverlayClick(event: MouseEvent): void {
    if ((event.target as HTMLElement).classList.contains('modal-overlay')) {
      this.closeModal();
    }
  }

  async submit(): Promise<void> {
    const fmt = this.selectedFormat();
    if (!fmt) return;
    if (this.templateRequired() && !this.templateFile()) {
      this.formError.set('A template file is required for PowerPoint exports.');
      return;
    }
    const messages = this.chat.messages()
      .filter(m => m.role === 'user' || m.role === 'assistant')
      .map(m => ({ role: m.role as 'user' | 'assistant', content: m.content || '' }));

    if (messages.length === 0) {
      this.formError.set('There is no conversation to export yet.');
      return;
    }

    try {
      await this.exporter.exportConversation(fmt as ExportFormat, messages, {
        templateFile: this.templateFile(),
      });
      const err = this.exporter.lastError();
      if (err) {
        this.formError.set(err);
        return;
      }
      this.closeModal();
    } catch (e: any) {
      this.formError.set(e?.message || 'Export failed.');
    }
  }
}
