import { Component, ChangeDetectionStrategy, inject } from '@angular/core';
import { SidebarComponent } from '../sidebar/sidebar.component';
import { ChatWindowComponent } from '../chat-window/chat-window.component';
import { ChatService } from '../../services/chat.service';

@Component({
  selector: 'app-shell',
  standalone: true,
  imports: [SidebarComponent, ChatWindowComponent],
  template: `
    <div class="app-shell" [class.sidebar-collapsed]="!chat.sidebarOpen()">
      <app-sidebar />
      <app-chat-window />
    </div>
  `,
  styles: [`
    :host {
      display: block;
      height: 100%;
      width: 100%;
    }

    .app-shell {
      display: flex;
      height: 100%;
      background: var(--bg-main, #f0f2f5);
    }

    .app-shell.sidebar-collapsed app-sidebar {
      display: none;
    }
  `],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AppShellComponent {
  readonly chat = inject(ChatService);
}
