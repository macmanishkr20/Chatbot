import { Component, inject, OnInit, signal, ChangeDetectionStrategy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ChatService } from '../../services/chat.service';
import { Conversation } from '../../models/chat.models';

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

  ngOnInit(): void {
    this.chat.loadConversations();
  }

  newChat(): void {
    this.chat.newChat();
  }

  selectConversation(conv: Conversation): void {
    this.chat.loadConversation(conv);
  }

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
  }

  cancelDelete(event: Event): void {
    event.stopPropagation();
    this.confirmDeleteId.set(null);
  }

  isActive(conv: Conversation): boolean {
    return this.chat.activeChatId() === conv.Id;
  }
}
