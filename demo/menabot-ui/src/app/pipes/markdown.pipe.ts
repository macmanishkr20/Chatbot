import { Pipe, PipeTransform } from '@angular/core';
import { DomSanitizer, SafeHtml } from '@angular/platform-browser';
import { marked } from 'marked';

@Pipe({
  name: 'markdown',
  standalone: true,
})
export class MarkdownPipe implements PipeTransform {
  constructor(private sanitizer: DomSanitizer) {
    marked.setOptions({
      breaks: true,
      gfm: true,
    });
  }

  transform(value: string | null | undefined): SafeHtml {
    if (!value) return '';
    try {
      let html = marked.parse(value) as string;

      // Style inline citation references like [1], [2], [1][2] as italic sky-blue
      html = html.replace(
        /\[(\d+)\](?![:(])/g,
        '<span class="citation-ref">[$1]</span>'
      );

      return this.sanitizer.bypassSecurityTrustHtml(html);
    } catch {
      return value;
    }
  }
}
