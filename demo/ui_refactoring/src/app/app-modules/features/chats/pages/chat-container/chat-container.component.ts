import { CommonModule } from '@angular/common';
import { Component, inject } from '@angular/core';
import { ChatInputComponent } from '../../components/chat-input/chat-input.component';
import { ChatHeaderComponent } from '../../components/chat-header/chat-header.component';
import { HomePromptDTO } from '../../models/chat.model';
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
    SvgIconComponent,
  ],
  templateUrl: './chat-container.component.html',
  styleUrls: ['./chat-container.component.scss'],
})
export class ChatContainerComponent {

  chatStore = inject(ChatStore);
  authService = inject(AuthService<AuthUser>);

  authUser = this.authService.user;
  homePrompts: HomePromptDTO[] = [];
  showFunctionFilter = true;

  constructor() {
    this.loadHomePrompts();
  }

  loadHomePrompts() {
    this.homePrompts = [
      {
        id: 1,
        title: 'What is the Purchase Order (PO) process?',
        prompt: 'What is the Purchase Order (PO) process?',
        serviceName: 'AWS',
      },
      {
        id: 2,
        title: 'What are the GCO Business Guidelines?',
        prompt: 'What are the GCO Business Guidelines?',
        serviceName: 'GCO',
      },
      {
        id: 3,
        title: 'What is the RFP Process?',
        prompt: 'What is the RFP Process?',
        serviceName: 'C&I',
      },
      {
        id: 4,
        title: 'What is the MENA Professional Qualification (PQ) Policy?',
        prompt: 'What is the MENA Professional Qualification (PQ) Policy?',
        serviceName: 'Talent',
      },
    ];
  }

  /** Legacy emit hook — chat-input now drives the store directly, so we just no-op here. */
  onSend(): void {
    // intentionally empty — ChatStore.sendMessage is invoked from chat-input
  }

  onSelectHomePrompt(prompt: HomePromptDTO): void {
    void this.chatStore.sendMessage(prompt.prompt);
  }
}
