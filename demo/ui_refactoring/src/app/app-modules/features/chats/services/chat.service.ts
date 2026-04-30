import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../../../../environments/environment';
import { ServiceResult } from '../../../../_shared/models/service-result';
import { ServiceHierarchyVM } from '../models/service-hierarchy';
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
 * Low-level chat API service — direct port of menabot-ui's `ApiService`.
 *
 * Talks to the FastAPI backend at `environment.apiBaseUrl`:
 *   - POST /chat                 (SSE stream)
 *   - POST /chat/edit            (SSE stream)
 *   - POST /chat/regenerate      (SSE stream)
 *   - POST /chat/cancel
 *   - GET  /conversations/{user_id}
 *   - GET  /conversations/{user_id}/{chat_id}/messages
 *   - DELETE /conversations/{user_id}/{chat_id}
 *   - PATCH  /conversations/{user_id}/{chat_id}/rename
 *   - POST /feedback
 *
 * The `getServiceHierarchies()` method is preserved — it powers the
 * ui_refactoring categorised feedback form (functions / sub-functions / services)
 * and is unrelated to the /chat pipeline.
 */
@Injectable({ providedIn: 'root' })
export class ChatService {
  private readonly http = inject(HttpClient);
  private readonly baseUrl = environment.apiBaseUrl;
  private readonly hierarchyUrl = `${environment.apiUrl}api/hierarchy`;

  // ── SSE Streaming (POST /chat, /chat/edit, /chat/regenerate) ──

  async *streamChat(body: ChatRequest, signal?: AbortSignal): AsyncGenerator<SSEEvent> {
    yield* this._streamPost(`${this.baseUrl}/chat`, body, signal);
  }

  async *streamEdit(body: EditRequest, signal?: AbortSignal): AsyncGenerator<SSEEvent> {
    yield* this._streamPost(`${this.baseUrl}/chat/edit`, body, signal);
  }

  async *streamRegenerate(body: RegenerateRequest, signal?: AbortSignal): AsyncGenerator<SSEEvent> {
    yield* this._streamPost(`${this.baseUrl}/chat/regenerate`, body, signal);
  }

  // ── REST Endpoints ──

  cancelChat(body: CancelRequest): Observable<{ status: string }> {
    return this.http.post<{ status: string }>(`${this.baseUrl}/chat/cancel`, body);
  }

  getConversations(userId: string): Observable<{ data: StoredConversation[] }> {
    return this.http.get<{ data: StoredConversation[] }>(
      `${this.baseUrl}/conversations/${encodeURIComponent(userId)}`,
    );
  }

  getMessages(userId: string, chatId: number): Observable<{ data: StoredMessage[] }> {
    return this.http.get<{ data: StoredMessage[] }>(
      `${this.baseUrl}/conversations/${encodeURIComponent(userId)}/${chatId}/messages`,
    );
  }

  deleteConversation(userId: string, chatId: number): Observable<{ status: string }> {
    return this.http.delete<{ status: string }>(
      `${this.baseUrl}/conversations/${encodeURIComponent(userId)}/${chatId}`,
    );
  }

  renameConversation(userId: string, chatId: number, body: RenameRequest): Observable<{ status: string; title: string }> {
    return this.http.patch<{ status: string; title: string }>(
      `${this.baseUrl}/conversations/${encodeURIComponent(userId)}/${chatId}/rename`,
      body,
    );
  }

  submitFeedback(body: FeedbackRequest): Observable<{ status: string }> {
    return this.http.post<{ status: string }>(`${this.baseUrl}/feedback`, body);
  }

  healthCheck(): Observable<{ status: string; engine: string }> {
    return this.http.get<{ status: string; engine: string }>(`${this.baseUrl}/health`);
  }

  // ── Existing ui_refactoring extension: feedback service hierarchy lookup ──

  getServiceHierarchies(): Observable<ServiceResult<ServiceHierarchyVM[]>> {
    return this.http.get<ServiceResult<ServiceHierarchyVM[]>>(`${this.hierarchyUrl}/get-all`);
  }

  // ── Private: SSE stream parser (verbatim from menabot-ui) ──

  private async *_streamPost(url: string, body: unknown, signal?: AbortSignal): AsyncGenerator<SSEEvent> {
    const response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
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
    } finally {
      reader.releaseLock();
    }
  }
}
