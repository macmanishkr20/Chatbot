import { Injectable, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { ApiService } from './api.service';
import { AuthService } from './auth.service';
import { ChatService } from './chat.service';
import {
  ExportFormat,
  ExportRequestBody,
  ExportResult,
} from '../models/chat.models';

/**
 * Document export service — completely decoupled from the chat pipeline.
 *
 * Two entry points:
 *   - exportMessage()      : per-message Word/Excel export (no template).
 *   - exportConversation() : header export (Word/Excel/PPT). PPT requires
 *                            an uploaded template; Word/Excel accept one
 *                            optionally.
 */
@Injectable({ providedIn: 'root' })
export class ExportService {
  private readonly api = inject(ApiService);
  private readonly auth = inject(AuthService);
  private readonly chat = inject(ChatService);

  /** Whether an export is currently in flight. */
  readonly busy = signal(false);
  readonly lastError = signal<string | null>(null);

  private get userId(): string {
    return this.auth.userEmail() || 'demo.user@gds.ey.com';
  }

  /** PPT requires a template; Word/Excel/TXT/JSON do not. */
  requiresTemplate(format: ExportFormat): boolean {
    return format === 'pptx';
  }

  /** Per-message export — no template prompt. */
  async exportMessage(format: ExportFormat, content: string, title?: string): Promise<void> {
    await this.run({
      user_id: this.userId,
      format,
      scope: 'message',
      content,
      title,
    });
  }

  /** Conversation export — caller decides whether to upload a template. */
  async exportConversation(
    format: ExportFormat,
    messages: { role: 'user' | 'assistant'; content: string }[],
    opts?: { templateFile?: File | null; title?: string },
  ): Promise<void> {
    let templateFileId: string | undefined;
    if (opts?.templateFile) {
      try {
        const upload = await firstValueFrom(
          this.api.uploadTemplate(this.userId, opts.templateFile),
        );
        templateFileId = upload.template_file_id;
      } catch (err) {
        console.error('Template upload failed:', err);
        this.lastError.set('Failed to upload template.');
        throw err;
      }
    }

    await this.run({
      user_id: this.userId,
      format,
      scope: 'conversation',
      messages,
      template_file_id: templateFileId,
      title: opts?.title,
    });
  }

  // ── Internal ──

  private async run(body: ExportRequestBody): Promise<void> {
    this.busy.set(true);
    this.lastError.set(null);
    try {
      const result = await firstValueFrom(this.api.export(body));
      this.triggerDownload(result);
    } catch (err: any) {
      console.error('Export failed:', err);
      const detail = err?.error?.detail || err?.message || 'Export failed';
      this.lastError.set(detail);
    } finally {
      this.busy.set(false);
    }
  }

  private triggerDownload(result: ExportResult): void {
    const url = this.api.buildDownloadUrl(result.url);
    const a = document.createElement('a');
    a.href = url;
    a.download = result.filename;
    a.target = '_blank';
    a.rel = 'noopener';
    document.body.appendChild(a);
    a.click();
    a.remove();
  }
}
