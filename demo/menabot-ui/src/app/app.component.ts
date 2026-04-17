import { Component, ChangeDetectionStrategy, inject } from '@angular/core';
import { SidebarComponent } from './components/sidebar/sidebar.component';
import { ChatWindowComponent } from './components/chat-window/chat-window.component';
import { ChatService } from './services/chat.service';

@Component({
  selector: 'app-root',
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
      background: #f0f2f5;
    }
  `],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AppComponent {
  readonly chat = inject(ChatService);
}
