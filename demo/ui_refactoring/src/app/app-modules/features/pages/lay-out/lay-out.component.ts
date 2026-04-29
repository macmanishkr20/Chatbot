import { Component } from '@angular/core';
import { ChatSidebarComponent } from '../../chats/components/chat-sidebar/chat-sidebar.component';

@Component({
  selector: 'app-lay-out',
  imports: [ChatSidebarComponent],
  templateUrl: './lay-out.component.html',
  styleUrls: ['./lay-out.component.scss'],
})
export class LayOutComponent {

}
