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
      height: 100vh;
      width: 100vw;
    }

    .app-shell {
      display: flex;
      height: 100%;
      background: var(--bg-main);
      color: var(--text-primary);
    }

    app-sidebar {
      flex-shrink: 0;
      overflow: hidden;
      width: 268px;
      transition: width 240ms cubic-bezier(0.4, 0, 0.2, 1),
                  opacity 180ms cubic-bezier(0.4, 0, 0.2, 1);
    }

    .app-shell.sidebar-collapsed app-sidebar {
      width: 0;
      opacity: 0;
      pointer-events: none;
    }
  `],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AppShellComponent {
  readonly chat = inject(ChatService);
}
