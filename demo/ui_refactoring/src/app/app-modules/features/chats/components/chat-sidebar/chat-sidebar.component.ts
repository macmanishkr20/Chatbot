import { CommonModule } from '@angular/common';
import { Component, inject, Input, OnInit } from '@angular/core';
import { NgbDropdownModule } from '@ng-bootstrap/ng-bootstrap';
import { ChatStore } from '../../services/chat.store';
import { RouterLink, RouterOutlet } from '@angular/router';
import { SideBarStore } from '../../services/sidebar.store';
import { SidebarCodes } from '../../../../../_shared/constants/sidebar';
import { NavItem } from '../../models/chat.model';
import { SvgIconComponent } from '../../../../../_shared/components/svg-icon/svg-icon.component';


@Component({
  selector: 'app-chat-sidebar',
  imports: [
    CommonModule,
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

  ngOnInit(): void {
    this.chatStore.loadConversations(true);
  }

  onLoadMoreConversations() {
    if (!this.chatStore.hasMoreConversations() || this.chatStore.loadingConversations()) {
      return;
    }

    this.chatStore.loadMoreConversations();
  }


  onGroupLabelClick(item: NavItem, event: MouseEvent): void {
    if (item.action) {
      event.preventDefault();
      item.action();
    }
  }

  /**
   * Get CSS classes for nav items based on nesting level
   */
  getItemClasses(level: number): string {
    const classes = ['nav-item-level-' + level];
    if (level === 0) {
      classes.push('nav-row');
    }
    if (level === 1) {
      classes.push('child-link');
    }
    if (level >= 2) {
      classes.push('grandchild-link');
    }
    return classes.join(' ');
  }

  /**
   * Get CSS classes for summary elements based on nesting level
   */
  getSummaryClasses(level: number): string {
    const classes = [];
    if (level > 0) {
      classes.push('child-summary');
    }
    return classes.join(' ');
  }

}
