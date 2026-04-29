import { CommonModule } from '@angular/common';
import { Component, ElementRef, EventEmitter, inject, Input, Output, ViewChild } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { ChatQueryDTO } from '../../models/chat.model';
import { AuthService } from '../../../../../_shared/messaging-service/auth.service';
import { AuthUser } from '../../../../../_shared/messaging-service/auth-user';
import { SvgIconComponent } from '../../../../../_shared/components/svg-icon/svg-icon.component';

@Component({
  selector: 'app-chat-input',
  imports: [
    CommonModule,
    ReactiveFormsModule,
    SvgIconComponent
  ],
  templateUrl: './chat-input.component.html',
  styleUrls: ['./chat-input.component.scss'],
})
export class ChatInputComponent {
private authUser = inject(AuthService<AuthUser>);
private formBuilder = inject(FormBuilder);

 @ViewChild('msg') textareaRef!: ElementRef<HTMLTextAreaElement>;


 @Input() placeholder = 'Type your question';
  @Input() disabled = false;
  @Input() ariaLabel = 'Chat message input';
  @Input() enterToSend = true;         // Enter sends, Shift+Enter newline
  @Input() shiftToNewLine = true;
  @Input() maxHeightPx = 160;          // max height for textarea auto-grow
  @Input() maxLength?: number;

  @Output() send = new EventEmitter<ChatQueryDTO>();
  @Output() attach = new EventEmitter<void>();

  userQueryForm = this.formBuilder.group({
    message: ['', [Validators.required]]
  });

  get form(){
    return this.userQueryForm.controls;
  }

  get message() { 
    return this.userQueryForm.get('message')?.value || ''; 
  }

  autoResize(el: HTMLTextAreaElement) {
    el.style.height = 'auto';
    const newHeight = Math.min(Math.max(el.scrollHeight, 24), this.maxHeightPx);
    el.style.height = newHeight + 'px';
  }

  onKeyDown(event: KeyboardEvent) {
    if (this.enterToSend && event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      this.onSend();
    }
  }

  onAttach() { 
    this.attach.emit(); 
  }
 
   onSend() {
    if(this.disabled) {
      return;
    }
    const userMessage = this.message?.trim();
    if(!userMessage) {
      return;
    }
    const chatMessage: ChatQueryDTO = {
        threadId: 1,
        queryId: Date.now().toString(),
        userQuery: userMessage,
        userEmail: this.authUser.user.email
      };
      this.send.emit(chatMessage);
      this.userQueryForm.reset();
      
      // Reset textarea height to initial state
      if (this.textareaRef?.nativeElement) {
        this.textareaRef.nativeElement.style.height = 'auto';
      }
  }
  
}
