import { HttpResponse } from '@angular/common/http';
import { Injectable } from '@angular/core';

@Injectable({
  providedIn: 'root',
})
export class DownloadService {
  /**
   * Triggers a browser file download from an HttpResponse<Blob>.
   *
   * Filename resolution order:
   *  1. `filename*` (RFC 5987 UTF-8 encoded) from Content-Disposition
   *  2. `filename` (plain) from Content-Disposition
   *  3. `fallbackName` parameter
   *
   * @param response   Full HTTP response carrying the blob body and headers.
   * @param fallbackName  Used when Content-Disposition carries no filename.
   */
  saveFile(response: HttpResponse<Blob>, fallbackName: string): void {
    const blob = response.body;
    if (!blob) {
        return;
    }

    const fileName = this.resolveFileName(response, fallbackName);
    const url = URL.createObjectURL(blob);

    try {
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = fileName;
      anchor.style.display = 'none';
      document.body.appendChild(anchor);
      anchor.click();
      document.body.removeChild(anchor);
    } finally {
      URL.revokeObjectURL(url);
    }
  }

  private resolveFileName(response: HttpResponse<Blob>, fallback: string): string {
    const disposition = response.headers.get('Content-Disposition') ?? '';
    if (!disposition) return fallback;

    // RFC 5987: filename*=charset''encoded-value  e.g. filename*=UTF-8''Report%20Final.xlsx
    const rfc5987 = disposition.match(/filename\*\s*=\s*(?:[^']*'')?([^;\s]+)/i);
    if (rfc5987?.[1]) {
      try {
        return decodeURIComponent(rfc5987[1]);
      } catch {
        // fall through to plain filename
      }
    }

    // Plain filename= — (?!\*) prevents accidentally matching filename*=
    const plain = disposition.match(/filename(?!\*)\s*=\s*"?([^";\n]+)"?/i);
    if (plain?.[1]?.trim()) {
      return plain[1].trim();
    }

    return fallback;
  }
}
