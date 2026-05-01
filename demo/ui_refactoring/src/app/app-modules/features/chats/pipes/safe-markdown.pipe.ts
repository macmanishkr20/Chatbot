import { Pipe, PipeTransform } from '@angular/core';
import { DomSanitizer, SafeHtml } from '@angular/platform-browser';
import { marked } from 'marked';

marked.use({
  breaks: true,
  gfm: true,
});

@Pipe({
  name: 'safeMarkdown',
  standalone: true,
  pure: false, // pure: false so it updates during streaming
})
export class SafeMarkdownPipe implements PipeTransform {
  private lastInput = '';
  private lastOutput: SafeHtml = '';

  constructor(private sanitizer: DomSanitizer) {}

  transform(value: string | null | undefined): SafeHtml {
    if (!value?.trim()) return '';
    if (value === this.lastInput) return this.lastOutput;

    try {
      // Step 1: Convert escaped newlines from DB to actual newlines
      let cleaned = value.replace(/\\n/g, '\n');

      // Step 2: Decode Unicode escapes (e.g., \u2019 -> ')
      cleaned = cleaned.replace(/\\u([\dA-Fa-f]{4})/g, (_, grp) =>
        String.fromCharCode(parseInt(grp, 16)),
      );

      // Step 3: Remove leading/trailing quotes if the entire string is wrapped
      cleaned = cleaned.replace(/^"(.*)"$/s, '$1');

      // Step 4: Auto-link bare URLs not already inside markdown link syntax
      cleaned = cleaned.replace(
        /(?<!\]\()(?<!")(?<!')\b(https?:\/\/[^\s<>\])]+)/g,
        '[$1]($1)',
      );

      let html = marked.parse(cleaned) as string;

      // Make all links open in a new tab
      html = html.replace(
        /<a\s+href="/g,
        '<a target="_blank" rel="noopener noreferrer" href="',
      );

      // Style inline citation references like [1], [2] as styled spans
      html = html.replace(
        /\[(\d+)\](?![:(])/g,
        '<span class="citation-ref">[$1]</span>',
      );

      this.lastInput = value;
      this.lastOutput = this.sanitizer.bypassSecurityTrustHtml(html);
      return this.lastOutput;
    } catch {
      return value;
    }
  }
}