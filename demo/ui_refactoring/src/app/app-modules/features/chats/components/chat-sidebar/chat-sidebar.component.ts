import { CommonModule } from '@angular/common';
import { Component, computed, inject, OnInit, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { NgbDropdownModule } from '@ng-bootstrap/ng-bootstrap';
import { ChatStore } from '../../services/chat.store';
import { RouterLink, RouterOutlet } from '@angular/router';
import { SideBarStore } from '../../services/sidebar.store';
import { SidebarCodes, SidebarNames } from '../../../../../_shared/constants/sidebar';
import { NavItem } from '../../models/chat.model';
import { SvgIconComponent } from '../../../../../_shared/components/svg-icon/svg-icon.component';
import { ConversationsVM } from '../../models/conversation';


@Component({
  selector: 'app-chat-sidebar',
  imports: [
    CommonModule,
    FormsModule,
    NgbDropdownModule,
    RouterLink,
    RouterOutlet,
    SvgIconComponent
  ],
  templateUrl: './chat-sidebar.component.html',
  styleUrls: ['./chat-sidebar.component.scss'],
})
export class ChatSidebarComponent implements OnInit {

  readonly chatStore = inject(ChatStore);
  sidebarStore = inject(SideBarStore);
  readonly SidebarCodes = SidebarCodes;

  sidebarCollapsed = true;
  conversationsExpanded = true;

  /** Client-side pagination */
  private readonly pageSize = 3;
  readonly visibleCount = signal(3);

  /** Pinned conversation IDs (client-side, persisted in localStorage) */
  readonly pinnedIds = signal<Set<number>>(new Set());

  readonly pinnedConversations = computed(() =>
    this.chatStore.chatConversations().filter(c => this.pinnedIds().has(c.id))
  );

  readonly unpinnedConversations = computed(() =>
    this.chatStore.chatConversations().filter(c => !this.pinnedIds().has(c.id))
  );

  readonly visibleConversations = computed(() =>
    this.unpinnedConversations().slice(0, this.visibleCount())
  );

  readonly hasMoreToShow = computed(() =>
    this.visibleCount() < this.unpinnedConversations().length
  );

  /** Rename state */
  renamingConvId: number | null = null;
  renameTitle = '';

  /** Admin sidebar items (kept unchanged) */
  adminItems: NavItem[] = [];

  ngOnInit(): void {
    this.chatStore.loadConversations(true);
    this.loadPinnedIds();

    const isSuperAdmin = this.chatStore.authUser()?.isSuperAdmin || false;
    this.adminItems = [
      {
        id: SidebarCodes.AdminDashboard,
        type: 'link',
        name: SidebarNames.AdminDashboard,
        code: SidebarCodes.AdminDashboard,
        icon: 'dashboard',
        // iconColorClass: 'icon-red',
        path: '/features/page/admin/dashboard',
        showInSidebar: isSuperAdmin
      },
      {
        id: SidebarCodes.AdminManagement,
        name: SidebarNames.AdminManagement,
        code: SidebarCodes.AdminManagement,
        type: 'link',
        icon: 'pc-check',
        // iconColorClass: 'icon-green',
        path: '/features/page/admin/user-management',
        showInSidebar: isSuperAdmin
      }
    ] as NavItem[];
  }

  onLoadMoreConversations() {
    this.visibleCount.update(count => count + this.pageSize);
  }

  onConversationsToggle(event: Event): void {
    const details = event.target as HTMLDetailsElement;
    this.conversationsExpanded = details.open;
  }

  expandIfCollapsed(): void {
    if (this.sidebarCollapsed) {
      this.sidebarCollapsed = false;
      // Programmatically uncheck the checkbox so CSS :checked state stays in sync
      const cb = document.getElementById('navCollapse') as HTMLInputElement;
      if (cb) cb.checked = false;
    }
  }

  onCollapseChange(event: Event): void {
    this.sidebarCollapsed = (event.target as HTMLInputElement).checked;
  }

  String(val: number): string {
    return String(val);
  }

  // ── Pin ──
  onPinConversation(conv: ConversationsVM): void {
    this.pinnedIds.update(ids => {
      const updated = new Set(ids);
      if (updated.has(conv.id)) {
        updated.delete(conv.id);
      } else {
        updated.add(conv.id);
      }
      return updated;
    });
    this.savePinnedIds();
  }

  isPinned(convId: number): boolean {
    return this.pinnedIds().has(convId);
  }

  // ── Rename ──
  onRenameConversation(conv: ConversationsVM): void {
    this.renamingConvId = conv.id;
    this.renameTitle = conv.title;
  }

  submitRename(conv: ConversationsVM): void {
    const newTitle = this.renameTitle.trim();
    if (newTitle && newTitle !== conv.title) {
      this.chatStore.renameConversation(conv, newTitle);
    }
    this.cancelRename();
  }

  cancelRename(): void {
    this.renamingConvId = null;
    this.renameTitle = '';
  }

  // ── Delete ──
  onDeleteConversation(conv: ConversationsVM): void {
    this.chatStore.deleteConversation(conv);
    // Also unpin if pinned
    if (this.pinnedIds().has(conv.id)) {
      this.pinnedIds.update(ids => {
        const updated = new Set(ids);
        updated.delete(conv.id);
        return updated;
      });
      this.savePinnedIds();
    }
  }

  // ── LocalStorage helpers for pins ──
  private loadPinnedIds(): void {
    try {
      const stored = localStorage.getItem('chat_pinned_ids');
      if (stored) {
        const arr = JSON.parse(stored) as number[];
        this.pinnedIds.set(new Set(arr));
      }
    } catch { /* ignore */ }
  }

  private savePinnedIds(): void {
    localStorage.setItem('chat_pinned_ids', JSON.stringify([...this.pinnedIds()]));
  }
}
