import { Pipe, PipeTransform } from '@angular/core';
import { DomSanitizer, SafeHtml } from '@angular/platform-browser';
import { marked } from 'marked';

@Pipe({
  name: 'markdown',
  standalone: true,
})
export class MarkdownPipe implements PipeTransform {
  private lastInput = '';
  private lastOutput: SafeHtml = '';

  constructor(private sanitizer: DomSanitizer) {
    marked.setOptions({
      breaks: true,
      gfm: true,
    });
  }

  transform(value: string | null | undefined): SafeHtml {
    if (!value) return '';
    // Skip re-parsing if input unchanged (same content rendered twice in one CD cycle)
    if (value === this.lastInput) return this.lastOutput;

    try {
      // Auto-link bare URLs that aren't already inside markdown link syntax.
      // Matches http/https URLs not preceded by ]( or "  (i.e. not already a link href).
      const autoLinked = value.replace(
        /(?<!\]\()(?<!")(?<!')\b(https?:\/\/[^\s<>\])]+)/g,
        '[$1]($1)'
      );

      let html = marked.parse(autoLinked) as string;

      // Make all links open in a new tab
      html = html.replace(
        /<a\s+href="/g,
        '<a target="_blank" rel="noopener noreferrer" href="'
      );

      // Style inline citation references like [1], [2], [1][2] as italic sky-blue
      html = html.replace(
        /\[(\d+)\](?![:(])/g,
        '<span class="citation-ref">[$1]</span>'
      );

      this.lastInput = value;
      this.lastOutput = this.sanitizer.bypassSecurityTrustHtml(html);
      return this.lastOutput;
    } catch {
      return value;
    }
  }
}
