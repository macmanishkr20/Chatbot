import { Component, ChangeDetectionStrategy, inject, input } from '@angular/core';
import { CommonModule } from '@angular/common';
import { DownloadInfo } from '../../models/chat.models';
import { ChatService } from '../../services/chat.service';

/** Inline card with a download button for a generated document. */
@Component({
  selector: 'app-download-card',
  standalone: true,
  imports: [CommonModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <a
      class="download-card"
      [href]="absoluteUrl()"
      [attr.download]="info().filename"
      target="_blank"
      rel="noopener"
    >
      <span class="mat-icon icon">{{ iconName() }}</span>
      <div class="meta">
        <div class="filename">{{ info().filename }}</div>
        <div class="format">{{ info().extension.toUpperCase() }} · click to download</div>
      </div>
      <span class="mat-icon arrow">download</span>
    </a>
    @if (info().ios_note) {
      <div class="ios-note">
        <span class="mat-icon">info</span>
        {{ info().ios_note }}
      </div>
    }
  `,
  styles: [`
    :host { display: block; margin-top: 8px; }
    .download-card {
      display: flex; align-items: center; gap: 12px;
      padding: 12px 14px;
      border: 1px solid var(--border, #e5e7eb);
      border-radius: 12px;
      background: linear-gradient(135deg, #2e2e38 0%, #3b3b46 100%);
      color: #fff;
      text-decoration: none;
      transition: transform 0.12s ease, box-shadow 0.12s ease;
    }
    .download-card:hover { transform: translateY(-1px); box-shadow: 0 6px 16px rgba(0,0,0,0.15); }
    .icon { font-size: 28px; color: #ffe600; }
    .meta { flex: 1; }
    .filename { font-weight: 600; font-size: 14px; word-break: break-all; }
    .format { font-size: 12px; opacity: 0.75; }
    .arrow { font-size: 22px; color: #ffe600; }
    .ios-note {
      margin-top: 6px; font-size: 12px; opacity: 0.8; display: flex; gap: 6px; align-items: flex-start;
    }
    .ios-note .mat-icon { font-size: 14px; }
  `],
})
export class DownloadCardComponent {
  private readonly chat = inject(ChatService);

  info = input.required<DownloadInfo>();

  readonly absoluteUrl = (): string => this.chat.downloadUrl(this.info().url);

  readonly iconName = (): string => {
    const ext = (this.info().extension || '').toLowerCase();
    if (ext === 'pptx') return 'slideshow';
    if (ext === 'xlsx') return 'table_chart';
    if (ext === 'docx') return 'description';
    if (ext === 'json') return 'data_object';
    return 'insert_drive_file';
  };
}
