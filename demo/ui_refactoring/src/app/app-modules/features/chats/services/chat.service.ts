import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../../../../environments/environment';
import { ServiceResult } from '../../../../_shared/models/service-result';
import { ServiceHierarchyVM } from '../models/service-hierarchy';
import { MsalService } from '@azure/msal-angular';
import {
  CancelRequest,
  ChatRequest,
  EditRequest,
  FeedbackRequest,
  RegenerateRequest,
  RenameRequest,
  SSEEvent,
  StoredConversation,
  StoredMessage,
} from '../models/chat.model';

/**
 * Low-level chat API service.
 *
 * Routes through the .NET gateway at `environment.apiUrl`:
 *   - POST /api/Chat/stream           (SSE stream)
 *   - POST /api/Chat/edit             (SSE stream)
 *   - POST /api/Chat/regenerate       (SSE stream)
 *   - POST /api/Chat/cancel
 *   - GET  /api/Chat/conversations
 *   - GET  /api/Chat/conversations/{chatId}/messages
 *   - DELETE /api/Chat/conversations/{chatId}
 *   - PATCH  /api/Chat/conversations/{chatId}/rename
 *   - POST /api/Feedback/post-feedback
 */
@Injectable({ providedIn: 'root' })
export class ChatService {
  private readonly http = inject(HttpClient);
  private readonly msalService = inject(MsalService);
  private readonly baseUrl = `${environment.apiUrl}api/Chat`;
  private readonly feedbackUrl = `${environment.apiUrl}api/Feedback`;
  private readonly hierarchyUrl = `${environment.apiUrl}api/hierarchy`;

  // ── SSE Streaming (POST /api/Chat/stream, /api/Chat/edit, /api/Chat/regenerate) ──

  async *streamChat(body: ChatRequest, signal?: AbortSignal): AsyncGenerator<SSEEvent> {
    yield* this._streamPost(`${this.baseUrl}/stream`, body, signal);
  }

  async *streamEdit(body: EditRequest, signal?: AbortSignal): AsyncGenerator<SSEEvent> {
    yield* this._streamPost(`${this.baseUrl}/edit`, body, signal);
  }

  async *streamRegenerate(body: RegenerateRequest, signal?: AbortSignal): AsyncGenerator<SSEEvent> {
    yield* this._streamPost(`${this.baseUrl}/regenerate`, body, signal);
  }

  // ── REST Endpoints ──

  cancelChat(body: CancelRequest): Observable<{ status: string }> {
    return this.http.post<{ status: string }>(`${this.baseUrl}/cancel`, body);
  }

  getConversations(_userId: string): Observable<{ data: StoredConversation[] }> {
    return this.http.get<{ data: StoredConversation[] }>(
      `${this.baseUrl}/conversations`,
    );
  }

  getMessages(_userId: string, chatId: number): Observable<{ data: StoredMessage[] }> {
    return this.http.get<{ data: StoredMessage[] }>(
      `${this.baseUrl}/conversations/${chatId}/messages`,
    );
  }

  deleteConversation(_userId: string, chatId: number): Observable<{ status: string }> {
    return this.http.delete<{ status: string }>(
      `${this.baseUrl}/conversations/${chatId}`,
    );
  }

  renameConversation(_userId: string, chatId: number, body: RenameRequest): Observable<{ status: string; title: string }> {
    return this.http.patch<{ status: string; title: string }>(
      `${this.baseUrl}/conversations/${chatId}/rename`,
      body,
    );
  }

  submitFeedback(body: FeedbackRequest): Observable<{ status: string }> {
    return this.http.post<{ status: string }>(`${this.feedbackUrl}/post-feedback`, body);
  }

  healthCheck(): Observable<{ status: string; engine: string }> {
    return this.http.get<{ status: string; engine: string }>(`${this.baseUrl}/health`);
  }

  // ── Existing ui_refactoring extension: feedback service hierarchy lookup ──

  getServiceHierarchies(): Observable<ServiceResult<ServiceHierarchyVM[]>> {
    return this.http.get<ServiceResult<ServiceHierarchyVM[]>>(`${this.hierarchyUrl}/get-all`);
  }

  // ── Private: SSE stream parser with MSAL token ──

  private async *_streamPost(url: string, body: unknown, signal?: AbortSignal): AsyncGenerator<SSEEvent> {
    const token = await this.getAccessToken();

    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }

    const response = await fetch(url, {
      method: 'POST',
      headers,
      body: JSON.stringify(body),
      signal,
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }

    const reader = response.body?.getReader();
    if (!reader) throw new Error('No response body');

    const decoder = new TextDecoder();
    let buffer = '';

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() ?? '';

        for (const line of lines) {
          const trimmed = line.trim();
          if (trimmed.startsWith('data: ')) {
            try {
              const event: SSEEvent = JSON.parse(trimmed.slice(6));
              yield event;
            } catch {
              // Skip malformed JSON lines
            }
          }
        }
      }

      // Process any remaining data left in the buffer after stream ends
      if (buffer.trim()) {
        const trimmed = buffer.trim();
        if (trimmed.startsWith('data: ')) {
          try {
            const event: SSEEvent = JSON.parse(trimmed.slice(6));
            yield event;
          } catch {
            // Skip malformed JSON
          }
        }
      }
    } finally {
      reader.releaseLock();
    }
  }

  private async getAccessToken(): Promise<string | null> {
    const account = this.msalService.instance.getActiveAccount();
    if (!account) return null;

    try {
      const result = await this.msalService.instance.acquireTokenSilent({
        scopes: [`api://${atob(environment.ccode)}/api-access`],
        account,
      });
      return result.accessToken;
    } catch {
      return null;
    }
  }
}