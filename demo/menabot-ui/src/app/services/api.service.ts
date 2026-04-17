import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../environments/environment';
import {
  CancelRequest,
  ChatRequest,
  Conversation,
  EditRequest,
  FeedbackRequest,
  RegenerateRequest,
  RenameRequest,
  SSEEvent,
  StoredMessage,
} from '../models/chat.models';

/**
 * Low-level API service — handles HTTP calls and SSE streaming
 * against the FastAPI backend.
 */
@Injectable({ providedIn: 'root' })
export class ApiService {
  private readonly http = inject(HttpClient);
  private readonly baseUrl = environment.apiBaseUrl;

  // ── SSE Streaming (POST /chat) ──

  /**
   * Stream chat response via fetch + ReadableStream.
   * EventSource doesn't support POST, so we use fetch with manual SSE parsing.
   *
   * Returns an AsyncGenerator that yields parsed SSEEvent objects.
   */
  async *streamChat(body: ChatRequest, signal?: AbortSignal): AsyncGenerator<SSEEvent> {
    yield* this._streamPost(`${this.baseUrl}/chat`, body, signal);
  }

  /**
   * Stream edited message response via POST /chat/edit.
   */
  async *streamEdit(body: EditRequest, signal?: AbortSignal): AsyncGenerator<SSEEvent> {
    yield* this._streamPost(`${this.baseUrl}/chat/edit`, body, signal);
  }

  /**
   * Stream regenerated response via POST /chat/regenerate.
   */
  async *streamRegenerate(body: RegenerateRequest, signal?: AbortSignal): AsyncGenerator<SSEEvent> {
    yield* this._streamPost(`${this.baseUrl}/chat/regenerate`, body, signal);
  }

  // ── REST Endpoints ──

  cancelChat(body: CancelRequest): Observable<{ status: string }> {
    return this.http.post<{ status: string }>(`${this.baseUrl}/chat/cancel`, body);
  }

  getConversations(userId: string): Observable<{ data: Conversation[] }> {
    return this.http.get<{ data: Conversation[] }>(
      `${this.baseUrl}/conversations/${encodeURIComponent(userId)}`
    );
  }

  getMessages(userId: string, chatId: number): Observable<{ data: StoredMessage[] }> {
    return this.http.get<{ data: StoredMessage[] }>(
      `${this.baseUrl}/conversations/${encodeURIComponent(userId)}/${chatId}/messages`
    );
  }

  deleteConversation(userId: string, chatId: number): Observable<{ status: string }> {
    return this.http.delete<{ status: string }>(
      `${this.baseUrl}/conversations/${encodeURIComponent(userId)}/${chatId}`
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

  // ── Private: SSE stream parser ──

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
