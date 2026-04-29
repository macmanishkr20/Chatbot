import { Pipe, PipeTransform } from '@angular/core';
import { marked, Renderer } from 'marked';
import DOMPurify from 'dompurify';

const renderer = new Renderer();

// Open links in new tab safely
renderer.link = ({ href, title, tokens }) => {
  const text = tokens.map(t => ('raw' in t ? t.raw : '')).join('');
  const titleAttr = title ? ` title="${title}"` : '';
  return `<a href="${href}"${titleAttr} target="_blank" rel="noopener noreferrer">${text}</a>`;
};

// Configure marked with options suitable for streaming content
marked.use({ 
  renderer,
  breaks: true,  // Enable line breaks
  gfm: true,     // GitHub Flavored Markdown
  pedantic: false // Be more lenient with markdown parsing
});

const ALLOWED_TAGS = [
  'p', 'strong', 'em', 'b', 'i', 'u', 's',
  'ul', 'ol', 'li',
  'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
  'blockquote', 'pre', 'code',
  'table', 'thead', 'tbody', 'tr', 'th', 'td',
  'br', 'hr',
  'a', 'span', 'div',
];

const ALLOWED_ATTR = ['href', 'title', 'target', 'rel', 'class'];

@Pipe({
  name: 'safeMarkdown',
  standalone: true,
  pure: false, // pure: false so it updates during streaming
})
export class SafeMarkdownPipe implements PipeTransform {
  transform(value: string | null | undefined): string {
    if (!value?.trim()) return '';

    // Step 1: Convert escaped newlines from DB to actual newlines
    let cleanedValue = value.replace(/\\n/g, '\n');

    // Step 2: Decode Unicode escapes (e.g., \u2019 -> ')
    cleanedValue = cleanedValue.replace(/\\u([\dA-Fa-f]{4})/g, (match, grp) => {
      return String.fromCharCode(parseInt(grp, 16));
    });

    // Step 3: Remove leading/trailing quotes if the entire string is wrapped
    cleanedValue = cleanedValue.replace(/^"(.*)"$/s, '$1');

    cleanedValue = cleanedValue.replace(/Citations:/gi, 'Source:');

    cleanedValue = cleanedValue.replace(/(https?:\/\/[^\]\s]+)\]/g, '$1 ]');

    const html = marked.parse(cleanedValue) as string;

    return DOMPurify.sanitize(html, {
      ALLOWED_TAGS,
      ALLOWED_ATTR,
      FORCE_BODY: false,
    });
  }
}
