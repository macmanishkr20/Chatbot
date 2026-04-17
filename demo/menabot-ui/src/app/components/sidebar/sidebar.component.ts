import { Component, inject, OnInit, signal, computed, ChangeDetectionStrategy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ChatService } from '../../services/chat.service';
import { Conversation } from '../../models/chat.models';

const PINNED_KEY = 'menabot_pinned_conversations';

@Component({
  selector: 'app-sidebar',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './sidebar.component.html',
  styleUrl: './sidebar.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class SidebarComponent implements OnInit {
  readonly chat = inject(ChatService);
  renamingId = signal<number | null>(null);
  renameText = signal('');
  confirmDeleteId = signal<number | null>(null);

  /** Collapsible state for Conversations section */
  conversationsExpanded = signal(true);

  /** Set of pinned conversation IDs (persisted in localStorage) */
  pinnedIds = signal<Set<number>>(new Set());

  /** Pinned conversations, filtered from full list */
  pinnedConversations = computed(() => {
    const ids = this.pinnedIds();
    return this.chat.conversations().filter(c => ids.has(c.Id));
  });

  /** Unpinned conversations */
  unpinnedConversations = computed(() => {
    const ids = this.pinnedIds();
    return this.chat.conversations().filter(c => !ids.has(c.Id));
  });

  ngOnInit(): void {
    this.chat.loadConversations();
    this.loadPinnedIds();
  }

  newChat(): void {
    this.chat.newChat();
  }

  selectConversation(conv: Conversation): void {
    this.chat.loadConversation(conv);
  }

  // ── Pin functionality ──

  togglePin(convId: number, event: Event): void {
    event.stopPropagation();
    const ids = new Set(this.pinnedIds());
    if (ids.has(convId)) {
      ids.delete(convId);
    } else {
      ids.add(convId);
    }
    this.pinnedIds.set(ids);
    this.savePinnedIds(ids);
  }

  isPinned(convId: number): boolean {
    return this.pinnedIds().has(convId);
  }

  toggleConversations(): void {
    this.conversationsExpanded.update(v => !v);
  }

  // ── Rename / Delete ──

  startRename(conv: Conversation, event: Event): void {
    event.stopPropagation();
    this.renamingId.set(conv.Id);
    this.renameText.set(conv.Title || '');
  }

  submitRename(conv: Conversation): void {
    const title = this.renameText().trim();
    if (title) {
      this.chat.renameConversation(conv, title);
    }
    this.renamingId.set(null);
  }

  cancelRename(): void {
    this.renamingId.set(null);
  }

  confirmDelete(conv: Conversation, event: Event): void {
    event.stopPropagation();
    this.confirmDeleteId.set(conv.Id);
  }

  doDelete(conv: Conversation, event: Event): void {
    event.stopPropagation();
    this.chat.deleteConversation(conv);
    this.confirmDeleteId.set(null);
    // Also unpin if it was pinned
    const ids = new Set(this.pinnedIds());
    if (ids.delete(conv.Id)) {
      this.pinnedIds.set(ids);
      this.savePinnedIds(ids);
    }
  }

  cancelDelete(event: Event): void {
    event.stopPropagation();
    this.confirmDeleteId.set(null);
  }

  isActive(conv: Conversation): boolean {
    return this.chat.activeChatId() === conv.Id;
  }

  // ── localStorage persistence ──

  private loadPinnedIds(): void {
    try {
      const raw = localStorage.getItem(PINNED_KEY);
      if (raw) {
        const arr = JSON.parse(raw) as number[];
        this.pinnedIds.set(new Set(arr));
      }
    } catch { /* ignore corrupt data */ }
  }

  private savePinnedIds(ids: Set<number>): void {
    localStorage.setItem(PINNED_KEY, JSON.stringify([...ids]));
  }
}
