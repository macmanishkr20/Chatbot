import { inject, Injectable, NgZone } from '@angular/core';
import { environment } from '../../../../../environments/environment';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { ServiceResult } from '../../../../_shared/models/service-result';
import { ChatMessagePaginationVM, ChatMessageDTO, ChatQueryDTO } from '../models/chat.model';
import { ConversationPaginationVM, ConversationRequestVM } from '../models/conversation';
import { FeedbackDTO, MessageFeedbackVM } from '../models/message-feedabck';
import { ServiceHierarchyVM } from '../models/service-hierarchy';
import { ActorType } from '../../../../_shared/constants/actor-type';
import { MsalService } from '@azure/msal-angular';

@Injectable({
  providedIn: 'root',
})
export class ChatService {
  private readonly chatUrl = `http://localhost:8000/chat`;
  private readonly conversationUrl = `${environment.apiUrl}api/conversation`;
  private readonly feedbackUrl = `http://localhost:8000/feedback`;
  private readonly hierarchyUrl = `${environment.apiUrl}api/hierarchy`;

  private readonly httpClient = inject(HttpClient);
  private readonly msalService = inject(MsalService);
  private readonly ngZone = inject(NgZone);

  // New Finalized APIs with Pagination and Feedback

  postMessage(chatQuery: ChatQueryDTO): Observable<ServiceResult<ChatMessageDTO>> {
    return this.httpClient.post<ServiceResult<ChatMessageDTO>>(`${this.chatUrl}/post-message`,
      chatQuery);
  }

  sendChatMessage(chatQuery: ChatQueryDTO): Observable<ServiceResult<ChatMessageDTO>> {
    return this.postMessage(chatQuery);
  }

  getMessagesByConversation(conversationRequest: ConversationRequestVM): Observable<ServiceResult<ChatMessagePaginationVM>> {
    return this.httpClient.post<ServiceResult<ChatMessagePaginationVM>>(`${this.chatUrl}/get-messages`,
      conversationRequest);
  }

  loadConversationMessages(conversationId: number, 
    userId: number,
    lastFetchedMessageId?: number, pageSize = 10): Observable<ServiceResult<ChatMessagePaginationVM>> {
    const request: ConversationRequestVM = {
      id: conversationId,
      userId,
      totalCount: 0,
      pageSize,
      lastFetchedMessageId,
    };

    return this.getMessagesByConversation(request);
  }

  getConversationsByUser(conversationRequest: ConversationRequestVM): Observable<ServiceResult<ConversationPaginationVM>> {
    return this.httpClient.post<ServiceResult<ConversationPaginationVM>>(`${this.conversationUrl}/get-conversations`, conversationRequest);
  }

  loadConversations(userId?: number, pageSize = 8, lastFetchedConversationId?: number): Observable<ServiceResult<ConversationPaginationVM>> {
    const request: ConversationRequestVM = {
      id: 0,
      userId,
      totalCount: 0,
      pageSize,
      lastFetchedConversationId
    };

    return this.getConversationsByUser(request);
  }

  postFeedback(feedback: FeedbackDTO): Observable<ServiceResult<boolean>> {
    return this.httpClient.post<ServiceResult<boolean>>(`${this.feedbackUrl}`, feedback);
  }

  getServiceHierarchies(): Observable<ServiceResult<ServiceHierarchyVM[]>> {
    return this.httpClient.get<ServiceResult<ServiceHierarchyVM[]>>(`${this.hierarchyUrl}/get-all`);
  }

  /**
   * Stream chat response with progressive updates.
   * Expects SSE format: `event: {type}\ndata: {jsonData}\n\n`
   * Handled event types: metadata, chunk, done, cancelled
   * @param chatQuery The chat query
   * @param onChunk Callback invoked for each streamed chunk of content
   * @param onComplete Callback invoked when streaming completes with final message data
   * @param onError Callback invoked if streaming fails or is cancelled
   */
  async streamChatResponse(
    chatQuery: ChatQueryDTO,
    onChunk: (chunk: string, fullContent: string) => void,
    onComplete?: (messageData: ChatMessageDTO) => void,
    onError?: (error: Error) => void,
    onThinkingChange?: (isThinking: boolean) => void
  ): Promise<void> {
    let reader: ReadableStreamDefaultReader<Uint8Array> | null = null;
    
    try {
      const accessToken = await this.acquireAccessToken();
      const response = await this.initiateStreamRequest(chatQuery, accessToken);
      
      reader = response.body?.getReader() ?? null;
      if (!reader) {
        throw new Error('Failed to get reader from response body');
      }
      
      const result = await this.readStreamChunks(reader, onChunk, (earlyResult) => {
        this.notifyStreamCompletion(earlyResult, onComplete);
      }, onThinkingChange);

      if (result.notifiedEarly !== true) {
        this.notifyStreamCompletion(result, onComplete);
      }
      
    } catch (error) {
      this.handleStreamError(error as Error, onError);
      throw error;
    } finally {
      await this.releaseReader(reader);
    }
  }

  /**
   * Acquire MSAL access token for API authentication
   */
  private async acquireAccessToken(): Promise<string> {
    const accounts = this.msalService.instance.getAllAccounts();
    if (accounts.length === 0) {
      throw new Error('No authenticated user found');
    }

    const tokenResponse = await this.msalService.instance.acquireTokenSilent({
      scopes: [`api://${atob(environment.ccode)}/api-access`],
      account: accounts[0]
    }).catch((tokenError) => {
      console.error('[Stream] Token acquisition failed:', tokenError);
      throw new Error(`Token acquisition failed: ${tokenError.message}`);
    });

    return tokenResponse.accessToken;
  }

  /**
   * Initiate streaming request to chat endpoint
   */
  private async initiateStreamRequest(
    chatQuery: ChatQueryDTO, 
    accessToken: string
  ): Promise<Response> {
    const response = await fetch(`${this.chatUrl}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${accessToken}`,
        'Accept': 'text/event-stream'
      },
      body: JSON.stringify(chatQuery),
      cache: 'no-cache'
    }).catch((fetchError) => {
      console.error('[Stream] Fetch failed:', fetchError);
      throw new Error(`Network request failed: ${fetchError.message}`);
    });

    if (!response.ok) {
      const errorText = await response.text().catch(() => 'Unknown error');
      console.error('[Stream] HTTP error:', response.status, errorText);
      throw new Error(`HTTP ${response.status}: ${errorText}`);
    }

    return response;
  }

  /**
   * Read and process stream chunks from the reader
   * Returns content and metadata (messageId, conversationId)
   */
  private async readStreamChunks(
    reader: ReadableStreamDefaultReader<Uint8Array>,
    onChunk: (chunk: string, fullContent: string) => void,
    onEarlyComplete?: (result: { content: string; messageId: string; 
      conversationId: string; metadataContent: string; chatSessionId?: string }) => void,
    onThinkingChange?: (isThinking: boolean) => void
  ): Promise<{ content: string; messageId: string; conversationId: string; 
    metadataContent?: string; chatSessionId?: string; notifiedEarly?: boolean }> {
    const decoder = new TextDecoder('utf-8');
    let fullContent = '';
    let buffer = '';
    let messageId = '';
    let conversationId = '';
    let metadataContent: string | undefined;
    let chatSessionId = '';
    let notifiedEarly = false;
    let supervisorResponseSeen = false;
    let supervisorClosingSeen = false;
    let supervisorDone = false;
    let generateNodeStarted = false;

    while (true) {
      const { value, done } = await reader.read();
      
      if (done) break;
      
      if (value) {
        buffer += decoder.decode(value, { stream: true });
        const messages = buffer.split(/\r?\n\r?\n/);
        buffer = messages.pop() || '';
        
        for (const message of messages) {
          if (!message.trim()) {
            continue;
          }
          
          const result = this.processSSEMessage(message, notifiedEarly ? null! : fullContent, notifiedEarly ? null! : onChunk, supervisorResponseSeen, supervisorClosingSeen, supervisorDone, generateNodeStarted);
          if (result.supervisorResponseSeen !== undefined) {
            supervisorResponseSeen = result.supervisorResponseSeen;
          }
          if (result.supervisorClosingSeen !== undefined) {
            supervisorClosingSeen = result.supervisorClosingSeen;
          }
          if (result.supervisorDone !== undefined) {
            supervisorDone = result.supervisorDone;
            if (result.supervisorDone) {
              this.ngZone.run(() => onThinkingChange?.(true));
            }
          }
          if (result.generateNodeStarted !== undefined) {
            generateNodeStarted = result.generateNodeStarted;
            if (result.generateNodeStarted) {
              this.ngZone.run(() => onThinkingChange?.(false));
            }
          }
          
          if (result.isMetadata) {
            messageId = result.messageId!;
            conversationId = result.conversationId!;
            chatSessionId = result.chatSessionId!;
            if (result.metadataContent && !notifiedEarly) {
              metadataContent = result.metadataContent;
              notifiedEarly = true;

              onEarlyComplete?.({ content: fullContent, messageId, conversationId, metadataContent, chatSessionId });
            }
          } else if (result.isComplete) {
            fullContent = result.content;
            // FastAPI 'final' event carries IDs alongside isComplete — capture them
            if (result.messageId) messageId = result.messageId;
            if (result.conversationId) conversationId = result.conversationId;
            return { content: fullContent, messageId, conversationId, metadataContent, chatSessionId, notifiedEarly };
          } else if (result.isCancelled) {
            throw new Error('Stream was cancelled by the server');
          } else if (!notifiedEarly) {
            fullContent = result.content;
          }
        }
      }
    }
    
    // Process any remaining buffer data (stream closed without trailing \n\n)
    if (buffer.trim()) {
      const result = this.processSSEMessage(buffer, notifiedEarly ? null! : fullContent, notifiedEarly ? null! : onChunk, supervisorResponseSeen, supervisorClosingSeen, supervisorDone, generateNodeStarted);
      if (result.isCancelled) {
        throw new Error('Stream was cancelled by the server');
      }
      if (!notifiedEarly) fullContent = result.content;
    }
    
    return { content: fullContent, messageId, conversationId, metadataContent, chatSessionId, notifiedEarly };
  }

  /**
   * Process a single SSE message in `event: {type}\ndata: {json}\n\n` format.
   * Handles metadata, chunk, done, cancelled event types and new FastAPI structured events.
   */
  private processSSEMessage(
    message: string,
    currentContent: string,
    onChunk: (chunk: string, fullContent: string) => void,
    supervisorResponseSeen = false,
    supervisorClosingSeen = false,
    supervisorDone = false,
    generateNodeStarted = false
  ): { content: string; isComplete: boolean; isCancelled: boolean; 
    isMetadata: boolean; messageId?: string; conversationId?: string; metadataContent?: string; 
    chatSessionId?: string; supervisorResponseSeen?: boolean; supervisorClosingSeen?: boolean;
    supervisorDone?: boolean; generateNodeStarted?: boolean } {
    let fullContent = currentContent;
    let eventType = '';
    let data = '';

    for (const line of message.split('\n')) {
      if (line.startsWith('event: ')) {
        eventType = line.substring(7).trim();
      } else if (line.startsWith('data: ')) {
        data = line.substring(6).replace(/\r$/, '');
      }
    }

    // Handle new FastAPI structured events (event: data OR event: chunk with JSON payload)
    if (eventType === 'data' || eventType === 'chunk' 
      || eventType === '') {
      const structuredEvent = this.tryParseFastApiEvent(data);
      if (structuredEvent) {
        // Handle type: "final" - stream is complete; capture IDs and stop.
        // Treating it as isComplete so the loop exits immediately and no further
        // content events (including any ai_content echo) are processed.
        if (structuredEvent.type === 'final') {
          return this.handleFinalEvent(structuredEvent, fullContent, onChunk, generateNodeStarted, supervisorDone);
        }
        //valid nodes for now
        const validNodes = ['generate', 'search'];
        let updatedSupervisorResponseSeen = supervisorResponseSeen;
        let updatedSupervisorClosingSeen = supervisorClosingSeen;
        let updatedSupervisorDone = supervisorDone;
        let updatedGenerateNodeStarted = generateNodeStarted;

        if (structuredEvent.type === 'content') {
          if (validNodes.includes(structuredEvent.node || '') && structuredEvent.content) {
            // generate/search: if supervisor content was shown, reset so generate text replaces it
            if (supervisorDone && !generateNodeStarted) {
              fullContent = structuredEvent.content;
              updatedGenerateNodeStarted = true;
            } else {
              fullContent += structuredEvent.content;
            }
            this.ngZone.run(() => onChunk(structuredEvent.content!, fullContent));
          } else if (structuredEvent.node === 'Supervisor' && !supervisorDone) {
            if (structuredEvent.content === 'response') {
              // Marker 1: start tracking
              updatedSupervisorResponseSeen = true;
            } else if (supervisorResponseSeen && structuredEvent.content === '}') {
              // Marker 2: '}'  — the very next Supervisor chunk is the final complete message
              updatedSupervisorClosingSeen = true;
            } else if (supervisorClosingSeen && structuredEvent.content) {
              // This is the final complete Supervisor message — show it, then mark done
              fullContent += structuredEvent.content;
              updatedSupervisorDone = true;
              this.ngZone.run(() => onChunk(structuredEvent.content!, fullContent));
            }
            // All other Supervisor chunks (before markers) are ignored
          }
        }

        // Ignore other nodes (persist, etc.) and thoughts
        return { content: fullContent, isComplete: false, isCancelled: false, isMetadata: false,
          supervisorResponseSeen: updatedSupervisorResponseSeen,
          supervisorClosingSeen: updatedSupervisorClosingSeen,
          supervisorDone: updatedSupervisorDone,
          generateNodeStarted: updatedGenerateNodeStarted };
      }
    }

    // Legacy event handling (only reached when data is NOT a FastAPI JSON object)
    switch (eventType) {
      case 'metadata': {
        const metadata = this.tryParseMetadata(data);
        if (metadata) {
          // Check if this is a type:final metadata event
          const metadataType = this.extractJsonStringField(data, '"Type"');
          if (metadataType === 'final') {
            return {
              content: fullContent,
              isComplete: true,
              isCancelled: false,
              isMetadata: false,
              messageId: metadata.messageId,
              conversationId: metadata.conversationId,
              chatSessionId: metadata.chatSessionId
            };
          }
          return {
            content: fullContent,
            isComplete: false,
            isCancelled: false,
            isMetadata: true,
            messageId: metadata.messageId,
            conversationId: metadata.conversationId,
            metadataContent: metadata.content,
            chatSessionId: metadata.chatSessionId
          };
        }
        break;
      }
      case 'chunk':
        if (data) {
          let chunkContent: string | null = data;
          try {
            const parsed = JSON.parse(data);
            if (typeof parsed === 'object' && parsed !== null) {
              // Direct JSON object on chunk event
              if (parsed.type === 'final') {
                return { content: fullContent, isComplete: true, isCancelled: false, isMetadata: false, messageId: parsed.message_id, conversationId: parsed.chat_id };
              }
              chunkContent = null; // any other object — drop
            } else if (typeof parsed === 'string') {
              // JSON-encoded string — the actual text may itself be a JSON object (e.g. final event double-encoded)
              try {
                const inner = JSON.parse(parsed);
                if (typeof inner === 'object' && inner !== null) {
                  if (inner.type === 'final') {
                    return { content: fullContent, isComplete: true, isCancelled: false, isMetadata: false, messageId: inner.message_id, conversationId: inner.chat_id };
                  }
                  chunkContent = null; // other structured object — drop
                } else {
                  chunkContent = parsed; // plain decoded string
                }
              } catch {
                chunkContent = parsed; // not JSON, use as plain text
              }
            }
          } catch {
            chunkContent = data; // not JSON at all — use raw
          }

          if (chunkContent !== null) {
            fullContent += chunkContent;
            this.ngZone.run(() => onChunk(chunkContent!, fullContent));
          }
        }
        break;
      case 'cancelled':
        return { content: fullContent, isComplete: false, isCancelled: true, isMetadata: false };
    }

    return { content: fullContent, isComplete: false, isCancelled: false, isMetadata: false };
  }

  
  private handleFinalEvent(
    event: { type: string; content?: string; node?: string; message?: string;
      chat_id?: string; message_id?: string; ai_content?: string },
    currentContent: string,
    onChunk: (chunk: string, fullContent: string) => void,
    generateNodeStarted: boolean,
    supervisorDone: boolean
  ): { content: string; isComplete: boolean; isCancelled: boolean; isMetadata: boolean;
    messageId?: string; conversationId?: string; metadataContent?: string; chatSessionId?: string } {
    let fullContent = currentContent;
    const noStreamedContent = !generateNodeStarted && !supervisorDone && !fullContent.trim();

    if (noStreamedContent) {
      const aiContent = event.ai_content?.trim();
      fullContent = aiContent || 'Something went wrong. Please try again with new chat.';
      this.ngZone.run(() => onChunk(fullContent, fullContent));
    }

    return {
      content: fullContent,
      isComplete: true,
      isCancelled: false,
      isMetadata: false,
      messageId: event.message_id,
      conversationId: event.chat_id,
      metadataContent: undefined,
      chatSessionId: undefined
    };
  }

  /**
   * Try to parse metadata JSON from an SSE metadata event's data field.
   * Returns metadata object if valid, null otherwise.
   */
  private tryParseMetadata(data: string): 
  { messageId: string; conversationId: string; content?: string; chatSessionId?: string } | null {
    try {
      const msgId = this.extractJsonStringField(data, '"MessageId"');
      if (!msgId) return null;
      const convId = this.extractJsonStringField(data, '"ConversationId"') ?? '';
      const content = this.extractContentField(data);
      const chatSessionId = this.extractJsonStringField(data, '"ChatSessionId"');
      return { messageId: msgId, conversationId: convId, content, chatSessionId };
    } catch {
      return null;
    }
  }

  /**
   * Try to parse FastAPI structured event
   * Format: {"type":"content"|"thought"|"final", "content":"...", "node":"generate"|"Supervisor"|..., ...}
   * Note: `node` is optional — `type:"final"` events may omit it.
   */
  private tryParseFastApiEvent(data: string): 
  { type: string; content?: string; node?: string; message?: string; 
    chat_id?: string; message_id?: string; ai_content?: string } | null {
    try {
      const parsed = JSON.parse(data);
      if (parsed && typeof parsed.type === 'string') {
        return parsed;
      }
      return null;
    } catch {
      return null;
    }
  }

  /** Extracts a short string field value by key from a JSON string using indexOf — no full parse. */
  private extractJsonStringField(data: string, key: string): string | undefined {
    const keyIdx = data.indexOf(key);
    if (keyIdx === -1) return undefined;
    const qOpen = data.indexOf('"', data.indexOf(':', keyIdx) + 1);
    if (qOpen === -1) return undefined;
    const qClose = data.indexOf('"', qOpen + 1);
    if (qClose === -1) return undefined;
    return data.slice(qOpen + 1, qClose);
  }

  /** Extracts the Content field, handling escape sequences inline for maximum speed. */
  private extractContentField(data: string): string | undefined {
    const keyIdx = data.indexOf('"Content"');
    if (keyIdx === -1) return undefined;
    const qOpen = data.indexOf('"', data.indexOf(':', keyIdx) + 1);
    if (qOpen === -1) return undefined;
    let qClose = qOpen + 1;
    while (qClose < data.length) {
      if (data[qClose] === '\\') { qClose += 2; continue; }
      if (data[qClose] === '"') break;
      qClose++;
    }
    return data.slice(qOpen + 1, qClose)
      .replace(/\\n/g, '\n')
      .replace(/\\r/g, '\r')
      .replace(/\\t/g, '\t')
      .replace(/\\"/g, '"')
      .replace(/\\\\/g, '\\');
  }

  /**
   * Notify completion callback with final message
   */
  private notifyStreamCompletion(
    result: { content: string; messageId: string; conversationId: string; metadataContent?: string; chatSessionId?: string },
    onComplete?: (messageData: ChatMessageDTO) => void
  ): void {
    if (!onComplete) return;
    
    this.ngZone.run(() => {
      const finalMessage: ChatMessageDTO = {
        id: 0,
        messageId: result.messageId,
        conversationId: result.conversationId,
        actor: ActorType.Bot,
        // content: result.metadataContent?.trim() ? result.metadataContent : result.content,
        content: result.content,
        chatSessionId: result.chatSessionId,
        createdAt: new Date(),
        metaData: [],
      };
      onComplete(finalMessage);
    });
  }

  /**
   * Handle streaming errors
   */
  private handleStreamError(
    error: Error,
    onError?: (error: Error) => void
  ): void {
    console.error('[Stream] Error occurred:', error);
    console.error('[Stream] Error details:', {
      message: error.message,
      name: error.name,
      stack: error.stack
    });
    
    this.ngZone.run(() => {
      onError?.(error);
    });
  }

  /**
   * Release stream reader resources
   */
  private async releaseReader(
    reader: ReadableStreamDefaultReader<Uint8Array> | null
  ): Promise<void> {
    if (reader) {
      try {
        await reader.cancel();
      } catch (e) {
        // Ignore cancellation errors
      }
    }
  }
}
