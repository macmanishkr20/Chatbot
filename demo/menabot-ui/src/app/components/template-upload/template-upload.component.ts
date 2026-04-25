import {
  Component,
  ChangeDetectionStrategy,
  inject,
  input,
  signal,
  ElementRef,
  ViewChild,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { ChatService } from '../../services/chat.service';
import { TemplateRequest } from '../../models/chat.models';

/**
 * Inline upload widget rendered inside an assistant bubble when the
 * backend signals it needs a template before generating a document.
 */
@Component({
  selector: 'app-template-upload',
  standalone: true,
  imports: [CommonModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="template-upload-card">
      <div class="header">
        <span class="mat-icon icon">upload_file</span>
        <div>
          <div class="title">Upload {{ extension().toUpperCase() }} template</div>
          <div class="subtitle">I'll edit your template directly to keep your branding.</div>
        </div>
      </div>

      <input
        #fileInput
        type="file"
        [accept]="'.' + extension()"
        (change)="onFileSelected($event)"
        hidden
      />

      @if (!selectedName()) {
        <button class="upload-btn" (click)="fileInput.click()" [disabled]="busy()">
          <span class="mat-icon">attach_file</span>
          Choose .{{ extension() }} file
        </button>
      } @else {
        <div class="file-row">
          <span class="mat-icon">description</span>
          <span class="file-name">{{ selectedName() }}</span>
          <button class="link-btn" (click)="fileInput.click()" [disabled]="busy()">Change</button>
        </div>
        <div class="actions">
          <button class="primary" (click)="submit()" [disabled]="busy()">
            {{ busy() ? 'Uploading…' : 'Upload & Generate' }}
          </button>
        </div>
      }

      @if (errorMsg()) {
        <div class="err">{{ errorMsg() }}</div>
      }
    </div>
  `,
  styles: [`
    :host { display: block; margin-top: 8px; }
    .template-upload-card {
      border: 1px dashed var(--border, #d1d5db);
      border-radius: 12px;
      padding: 14px 16px;
      background: var(--surface-2, #fafafa);
      display: flex; flex-direction: column; gap: 12px;
    }
    .header { display: flex; gap: 12px; align-items: center; }
    .header .icon { font-size: 28px; color: #ffe600; background: #2e2e38; padding: 6px; border-radius: 8px; }
    .title { font-weight: 600; font-size: 14px; }
    .subtitle { font-size: 12px; opacity: 0.75; }
    .upload-btn, .actions .primary {
      background: #2e2e38; color: #ffe600; border: none; padding: 8px 14px;
      border-radius: 8px; font-weight: 600; cursor: pointer; display: inline-flex;
      align-items: center; gap: 8px;
    }
    .upload-btn:disabled, .actions .primary:disabled { opacity: 0.6; cursor: not-allowed; }
    .file-row { display: flex; align-items: center; gap: 8px; font-size: 13px; }
    .file-name { font-family: monospace; word-break: break-all; }
    .link-btn { background: none; border: none; color: #4b5563; text-decoration: underline; cursor: pointer; }
    .err { color: #c0392b; font-size: 12px; }
    .actions { display: flex; justify-content: flex-end; }
  `],
})
export class TemplateUploadComponent {
  private readonly chat = inject(ChatService);

  request = input.required<TemplateRequest>();

  readonly busy = signal(false);
  readonly errorMsg = signal<string | null>(null);
  readonly selectedName = signal<string>('');
  private selectedFile: File | null = null;

  @ViewChild('fileInput') fileInput!: ElementRef<HTMLInputElement>;

  readonly extension = (): string => this.request().extension || 'pptx';

  onFileSelected(event: Event): void {
    this.errorMsg.set(null);
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) return;
    const ext = file.name.split('.').pop()?.toLowerCase() ?? '';
    if (ext !== this.extension().toLowerCase()) {
      this.errorMsg.set(`Please upload a .${this.extension()} file.`);
      input.value = '';
      return;
    }
    this.selectedFile = file;
    this.selectedName.set(file.name);
  }

  async submit(): Promise<void> {
    if (!this.selectedFile || this.busy()) return;
    this.busy.set(true);
    this.errorMsg.set(null);
    try {
      await this.chat.submitTemplate(
        this.selectedFile,
        this.request().format,
        this.request().topic,
      );
    } catch (e) {
      console.error(e);
      this.errorMsg.set('Upload failed — please try again.');
    } finally {
      this.busy.set(false);
    }
  }
}
