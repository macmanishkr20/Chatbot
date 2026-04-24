import { Injectable, inject, signal } from '@angular/core';
import { environment } from '../environments/environment';
import { ChatService } from './chat.service';

/**
 * Client for the screen-share + voice assistance backend.
 *
 * Opens two WebSockets against the FastAPI backend:
 *   - `/ws/screenshare/signaling` — WebRTC offer/answer handshake
 *   - `/ws/screenshare/control`   — transcript + assistant events
 *
 * Captures the user's microphone and (optionally) their screen via
 * ``getDisplayMedia``, sends them as WebRTC tracks to the backend, and
 * plays the backend's spoken reply through an auto-playing `<audio>`.
 *
 * Events from the control channel are routed into ``ChatService``'s
 * voice-ingest helpers so the user bubble and assistant bubble render
 * in the chat window exactly as typed messages do. Persistence /
 * checkpointing / memory all happen server-side.
 */
@Injectable({ providedIn: 'root' })
export class ScreenshareService {
  private readonly chat = inject(ChatService);

  // ── Public reactive state ──
  readonly isActive = signal(false);
  readonly status = signal<'idle' | 'connecting' | 'live' | 'error'>('idle');
  readonly userSpeaking = signal(false);
  readonly assistantSpeaking = signal(false);
  readonly errorMessage = signal<string | null>(null);

  // ── Internals ──
  private pc: RTCPeerConnection | null = null;
  private signalingWs: WebSocket | null = null;
  private controlWs: WebSocket | null = null;
  private micStream: MediaStream | null = null;
  private screenStream: MediaStream | null = null;
  private playbackAudio: HTMLAudioElement | null = null;
  private streamingAssistantMsgId: string | null = null;
  private sessionId: string | null = null;

  async toggle(): Promise<void> {
    if (this.isActive()) {
      await this.stop();
    } else {
      await this.start();
    }
  }

  async start(): Promise<void> {
    if (this.isActive() || this.status() === 'connecting') return;
    this.status.set('connecting');
    this.errorMessage.set(null);

    try {
      // Ensure a chat session exists; the backend keys persistence on
      // `${user_id}_${chat_session_id}` — same as the REST /chat path.
      if (!this.chat.activeSessionId()) {
        this.chat.newChat();
      }
      this.sessionId = this.makeSessionId();

      // ── 1. Capture user media (mic first, screen optional) ──
      this.micStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
        },
      });
      try {
        this.screenStream = await navigator.mediaDevices.getDisplayMedia({
          video: true,
          audio: false,
        });
        // User-initiated stop from the browser's share dialog → tear down.
        this.screenStream
          .getVideoTracks()[0]
          .addEventListener('ended', () => void this.stop());
      } catch (err) {
        // User declined the picker — proceed with voice-only.
        console.warn('screenshare: screen picker cancelled, voice-only', err);
        this.screenStream = null;
      }

      // ── 2. Build the peer connection ──
      this.pc = new RTCPeerConnection();
      for (const t of this.micStream.getTracks()) {
        this.pc.addTrack(t, this.micStream);
      }
      if (this.screenStream) {
        for (const t of this.screenStream.getTracks()) {
          this.pc.addTrack(t, this.screenStream);
        }
      }
      this.pc.ontrack = (ev) => this.attachRemoteAudio(ev.streams[0]);

      // ── 3. Open the control WebSocket (events) ──
      const qs = this.buildQuery();
      const wsBase = environment.apiBaseUrl.replace(/^http/, 'ws');

      this.controlWs = new WebSocket(
        `${wsBase}/ws/screenshare/control?${qs}`,
      );
      this.controlWs.addEventListener('message', (ev) =>
        this.handleControlEvent(ev.data),
      );
      this.controlWs.addEventListener('close', () => {
        if (this.isActive()) void this.stop();
      });
      await this.waitForOpen(this.controlWs);

      // ── 4. Open the signaling WebSocket and exchange SDP ──
      this.signalingWs = new WebSocket(
        `${wsBase}/ws/screenshare/signaling?${qs}`,
      );
      await this.waitForOpen(this.signalingWs);

      const offer = await this.pc.createOffer();
      await this.pc.setLocalDescription(offer);

      const answerPromise = new Promise<void>((resolve, reject) => {
        const onMessage = async (ev: MessageEvent) => {
          try {
            const msg = JSON.parse(ev.data as string);
            if (msg.type === 'answer') {
              await this.pc!.setRemoteDescription({
                type: msg.sdpType,
                sdp: msg.sdp,
              });
              resolve();
            } else if (msg.type === 'error') {
              reject(new Error(msg.message || 'signaling error'));
            }
          } catch (err) {
            reject(err);
          }
        };
        this.signalingWs!.addEventListener('message', onMessage, {
          once: false,
        });
      });

      this.signalingWs.send(
        JSON.stringify({
          type: 'offer',
          sdp: offer.sdp,
          sdpType: offer.type,
        }),
      );
      await answerPromise;

      this.isActive.set(true);
      this.status.set('live');
    } catch (err) {
      console.error('screenshare: start failed', err);
      this.errorMessage.set(
        err instanceof Error ? err.message : 'Failed to start screen share',
      );
      this.status.set('error');
      await this.stop();
    }
  }

  async stop(): Promise<void> {
    this.isActive.set(false);
    if (this.status() !== 'error') this.status.set('idle');
    this.userSpeaking.set(false);
    this.assistantSpeaking.set(false);
    this.streamingAssistantMsgId = null;

    try {
      this.pc?.close();
    } catch {
      /* noop */
    }
    this.pc = null;

    try {
      this.signalingWs?.close();
    } catch {
      /* noop */
    }
    this.signalingWs = null;

    try {
      this.controlWs?.close();
    } catch {
      /* noop */
    }
    this.controlWs = null;

    this.micStream?.getTracks().forEach((t) => t.stop());
    this.micStream = null;
    this.screenStream?.getTracks().forEach((t) => t.stop());
    this.screenStream = null;

    if (this.playbackAudio) {
      this.playbackAudio.pause();
      this.playbackAudio.srcObject = null;
      this.playbackAudio.remove();
      this.playbackAudio = null;
    }
  }

  // ── Internals ──

  private attachRemoteAudio(stream: MediaStream): void {
    if (!this.playbackAudio) {
      this.playbackAudio = document.createElement('audio');
      this.playbackAudio.autoplay = true;
      this.playbackAudio.style.display = 'none';
      document.body.appendChild(this.playbackAudio);
    }
    this.playbackAudio.srcObject = stream;
    this.playbackAudio.play().catch((err) => {
      // Autoplay may be blocked until a user gesture. The user already
      // clicked the screen-share button, so this should normally succeed,
      // but we log anyway for the rare case it doesn't.
      console.warn('screenshare: remote audio play blocked', err);
    });
  }

  private handleControlEvent(raw: unknown): void {
    let evt: any;
    try {
      evt = JSON.parse(raw as string);
    } catch {
      return;
    }

    switch (evt.type) {
      case 'hello':
        break;

      case 'transcript':
        if (evt.role === 'user' && evt.final) {
          this.chat.ingestVoiceUserMessage(evt.text || '');
        }
        break;

      case 'assistant':
        if (evt.final) {
          this.chat.ingestVoiceAssistantFinal(
            evt.text || '',
            this.streamingAssistantMsgId,
          );
          // keep streamingAssistantMsgId — ingestVoiceFinal still needs it
        } else if (evt.text) {
          this.streamingAssistantMsgId = this.chat.ingestVoiceAssistantDelta(
            evt.text,
            this.streamingAssistantMsgId,
          );
        }
        break;

      case 'speaking':
        if (evt.role === 'user') {
          this.userSpeaking.set(evt.state === 'start');
        } else {
          this.assistantSpeaking.set(evt.state === 'start');
        }
        break;

      case 'final':
        this.chat.ingestVoiceFinal(evt, this.streamingAssistantMsgId);
        this.streamingAssistantMsgId = null;
        break;

      case 'error':
        console.error('screenshare: backend error', evt.message);
        this.errorMessage.set(evt.message || 'Backend error');
        break;
    }
  }

  private buildQuery(): string {
    const params = new URLSearchParams({
      token: environment.screenshareToken,
      sessionId: this.sessionId!,
      userId: this.chat.userId(),
      chatSessionId: this.chat.activeSessionId() ?? '',
    });
    return params.toString();
  }

  private makeSessionId(): string {
    const buf = new Uint8Array(8);
    crypto.getRandomValues(buf);
    return Array.from(buf, (b) => b.toString(16).padStart(2, '0')).join('');
  }

  private waitForOpen(ws: WebSocket): Promise<void> {
    if (ws.readyState === WebSocket.OPEN) return Promise.resolve();
    return new Promise((resolve, reject) => {
      const onOpen = () => {
        cleanup();
        resolve();
      };
      const onError = (e: Event) => {
        cleanup();
        reject(new Error('WebSocket connection failed'));
      };
      const cleanup = () => {
        ws.removeEventListener('open', onOpen);
        ws.removeEventListener('error', onError);
      };
      ws.addEventListener('open', onOpen);
      ws.addEventListener('error', onError);
    });
  }
}
