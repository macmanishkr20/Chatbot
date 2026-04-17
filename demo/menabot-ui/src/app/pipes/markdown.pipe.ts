import { Pipe, PipeTransform } from '@angular/core';
import { DomSanitizer, SafeHtml } from '@angular/platform-browser';

/**
 * Transforms raw markdown text into sanitized HTML.
 *
 * Supports: headers, bold, italic, inline code, fenced code blocks,
 * tables, blockquotes, ordered/unordered lists, horizontal rules,
 * inline citation refs [1][2], and a collapsible citations accordion.
 */
@Pipe({ name: 'markdown', standalone: true })
export class MarkdownPipe implements PipeTransform {
  constructor(private sanitizer: DomSanitizer) {}

  transform(text: string | null | undefined): SafeHtml {
    if (!text) return '';
    const html = this.renderAnswer(text);
    return this.sanitizer.bypassSecurityTrustHtml(html);
  }

  // ── Top-level renderer ──

  private renderAnswer(text: string): string {
    const citMarker = /\nCitations:\n|^Citations:\n/;
    const splitIdx = text.search(citMarker);

    let mainText: string;
    let citationsRaw: string | null;

    if (splitIdx !== -1) {
      const match = text.match(citMarker)!;
      mainText = text.slice(0, splitIdx);
      citationsRaw = text.slice(splitIdx + match[0].length);
    } else {
      mainText = text;
      citationsRaw = null;
    }

    let html = this.renderMarkdown(mainText);

    if (citationsRaw !== null) {
      html += this.buildCitationsAccordion(citationsRaw);
    }

    return html;
  }

  // ── Block-level markdown ──

  private renderMarkdown(text: string): string {
    // Extract fenced code blocks first
    const codeBlocks: string[] = [];
    text = text.replace(/```(\w*)\n([\s\S]*?)```/g, (_, lang: string, code: string) => {
      const placeholder = `%%CODEBLOCK_${codeBlocks.length}%%`;
      const langLabel = lang
        ? `<span class="code-lang">${this.esc(lang)}</span>`
        : '';
      const copyBtn = `<button class="copy-btn" onclick="navigator.clipboard.writeText(this.closest('pre').querySelector('code').textContent).then(()=>{this.textContent='Copied!';setTimeout(()=>this.textContent='Copy',1500)})">Copy</button>`;
      codeBlocks.push(
        `<pre>${langLabel}${copyBtn}<code>${this.esc(code.trimEnd())}</code></pre>`
      );
      return placeholder;
    });

    const lines = text.split('\n');
    let html = '';
    let i = 0;

    while (i < lines.length) {
      const line = lines[i];

      // Code block placeholder
      const cbMatch = line.match(/^%%CODEBLOCK_(\d+)%%$/);
      if (cbMatch) {
        html += codeBlocks[parseInt(cbMatch[1], 10)];
        i++;
        continue;
      }

      // Table
      if (line.trim().startsWith('|') && line.trim().endsWith('|')) {
        const tableLines: string[] = [];
        while (
          i < lines.length &&
          lines[i].trim().startsWith('|') &&
          lines[i].trim().endsWith('|')
        ) {
          tableLines.push(lines[i]);
          i++;
        }
        html += this.renderTable(tableLines);
        continue;
      }

      // Headers
      if (line.startsWith('### ')) {
        html += `<h3>${this.renderInline(line.slice(4))}</h3>`;
        i++; continue;
      }
      if (line.startsWith('## ')) {
        html += `<h2>${this.renderInline(line.slice(3))}</h2>`;
        i++; continue;
      }
      if (line.startsWith('# ')) {
        html += `<h1>${this.renderInline(line.slice(2))}</h1>`;
        i++; continue;
      }

      // Horizontal rule
      if (/^---+$/.test(line.trim())) {
        html += '<hr>';
        i++; continue;
      }

      // Blockquote
      if (line.startsWith('> ')) {
        const quoteLines: string[] = [];
        while (i < lines.length && lines[i].startsWith('> ')) {
          quoteLines.push(lines[i].slice(2));
          i++;
        }
        html += `<blockquote>${this.renderInline(quoteLines.join('<br>'))}</blockquote>`;
        continue;
      }

      // Unordered list
      if (/^[-*] /.test(line.trimStart())) {
        const items: string[] = [];
        while (i < lines.length && /^[-*] /.test(lines[i].trimStart())) {
          items.push(lines[i].trimStart().slice(2));
          i++;
        }
        html +=
          '<ul>' +
          items.map(li => `<li>${this.renderInline(li)}</li>`).join('') +
          '</ul>';
        continue;
      }

      // Ordered list
      if (/^\d+\.\s/.test(line.trimStart())) {
        const items: string[] = [];
        while (i < lines.length && /^\d+\.\s/.test(lines[i].trimStart())) {
          items.push(lines[i].trimStart().replace(/^\d+\.\s/, ''));
          i++;
        }
        html +=
          '<ol>' +
          items.map(li => `<li>${this.renderInline(li)}</li>`).join('') +
          '</ol>';
        continue;
      }

      // Empty line
      if (line.trim() === '') {
        html += '<br>';
        i++;
        continue;
      }

      // Normal line
      html += this.renderInline(line) + '<br>';
      i++;
    }

    return html;
  }

  // ── Inline markdown ──

  private renderInline(text: string): string {
    return this.esc(text)
      .replace(/`([^`]+)`/g, '<code>$1</code>')
      .replace(/\*\*\*(.+?)\*\*\*/g, '<strong><em>$1</em></strong>')
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      .replace(/\*(.+?)\*/g, '<em>$1</em>')
      .replace(/(\[\d+\])+/g, m => `<em class="ref">${m}</em>`);
  }

  // ── Table ──

  private renderTable(lines: string[]): string {
    if (lines.length < 2) {
      return lines.map(l => this.renderInline(l) + '<br>').join('');
    }

    const parseRow = (line: string) =>
      line.split('|').slice(1, -1).map(c => c.trim());

    const headers = parseRow(lines[0]);
    const isSep = /^\|[\s\-:|]+\|$/.test(lines[1].trim());
    const dataStart = isSep ? 2 : 1;

    let html = '<table><thead><tr>';
    for (const h of headers) {
      html += `<th>${this.renderInline(h)}</th>`;
    }
    html += '</tr></thead><tbody>';

    for (let r = dataStart; r < lines.length; r++) {
      const cells = parseRow(lines[r]);
      html += '<tr>';
      for (const c of cells) {
        html += `<td>${this.renderInline(c)}</td>`;
      }
      html += '</tr>';
    }
    html += '</tbody></table>';
    return html;
  }

  // ── Citations accordion ──

  private buildCitationsAccordion(raw: string): string {
    const lines = raw.trim().split('\n').filter(l => l.trim());
    const citationLines = lines
      .map(line => {
        const m = line.match(/^((?:\[\d+\])+)\s+(https?:\/\/\S+)$/);
        if (m) {
          return (
            `<span class="cite-ref">${this.esc(m[1])}</span>&nbsp;` +
            `<a class="cite-url" href="${this.esc(m[2])}" target="_blank" rel="noopener">${this.esc(m[2])}</a>`
          );
        }
        return this.esc(line).replace(
          /(\[\d+\])+/g,
          match => `<em class="cite-ref">${match}</em>`
        );
      })
      .join('<br>');

    return `
      <div class="citations-accordion" onclick="this.classList.toggle('open')">
        <div class="citations-header">
          <span>&#128206; Citations</span>
          <span class="citations-caret">&#9654;</span>
        </div>
        <div class="citations-body">${citationLines}</div>
      </div>`;
  }

  // ── Escape HTML ──

  private esc(s: string): string {
    return s
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }
}
