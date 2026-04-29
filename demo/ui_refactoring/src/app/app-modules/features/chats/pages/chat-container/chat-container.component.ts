import { CommonModule } from '@angular/common';
import { Component, inject } from '@angular/core';
import { ChatInputComponent } from '../../components/chat-input/chat-input.component';
import { ChatHeaderComponent } from '../../components/chat-header/chat-header.component';
import { ChatQueryDTO, HomePromptDTO } from '../../models/chat.model';
import { ChatStore } from '../../services/chat.store';
import { RouterOutlet } from '@angular/router';
import { AuthService } from '../../../../../_shared/messaging-service/auth.service';
import { AuthUser } from '../../../../../_shared/messaging-service/auth-user';
import { SvgIconComponent } from '../../../../../_shared/components/svg-icon/svg-icon.component';

@Component({
  selector: 'app-chat-container',
  imports: [
    CommonModule,
    ChatInputComponent,
    ChatHeaderComponent,
    RouterOutlet,
    SvgIconComponent
  ],
  templateUrl: './chat-container.component.html',
  styleUrls: ['./chat-container.component.scss'],
})
export class ChatContainerComponent {

  chatStore = inject(ChatStore);
  authService = inject(AuthService<AuthUser>);

  authUser = this.authService.user;
  homePrompts: HomePromptDTO[] = [];


  constructor() {
    this.loadHomePrompts();

  }

  loadHomePrompts() {
    this.homePrompts = [{
      id: 1,
      title: 'What is the internal transfer process',
      prompt: 'What is the internal transfer process?',
      serviceName: 'Talent'
    },
    {
      id: 2,
      title: 'What is MENA Pursuit process',
      prompt: 'What is MENA Pursuit process',
      serviceName: 'C&I'
    },
    {
      id: 3,
      title: 'Where can I access the GCO templates?',
      prompt: 'Where can I access the GCO templates?',
      serviceName: 'GCO'
    },
    {
      id: 4,
      title: 'How do I submit  a BRIDGE request?',
      prompt: 'How do I submit  a BRIDGE request?',
      serviceName: 'Risk Management'
    }

    ];
  }

  onSend(userQuery: ChatQueryDTO) {
    this.enableStreaming(userQuery, true);
  }

  private enableStreaming(userQuery: ChatQueryDTO, isEnabled: boolean) {
    this.chatStore.enableStreaming.set(isEnabled);
    this.chatStore.sendMessage(userQuery);
  }

  onSelectHomePrompt(prompt: HomePromptDTO) {
    const userQuery: ChatQueryDTO = {
      userQuery: prompt.prompt,
      userEmail: this.authUser?.email,
      queryId: Date.now().toString(),
      threadId: 1,
    }
    this.onSend(userQuery);
  }
}
