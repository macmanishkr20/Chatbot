import { CommonModule } from '@angular/common';
import { Component, computed, inject, OnInit, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { ChatInputComponent } from '../../components/chat-input/chat-input.component';
import { ChatHeaderComponent } from '../../components/chat-header/chat-header.component';
import { HomePromptDTO } from '../../models/chat.model';
import { ChatStore } from '../../services/chat.store';
import { RouterOutlet } from '@angular/router';
import { AuthService } from '../../../../../_shared/messaging-service/auth.service';
import { AuthUser } from '../../../../../_shared/messaging-service/auth-user';
import { SvgIconComponent } from '../../../../../_shared/components/svg-icon/svg-icon.component';
import { OnboardingCardComponent } from '../../components/onboarding-card/onboarding-card.component';
import { ReportBuilderPanelComponent } from '../../components/report-builder-panel/report-builder-panel.component';
import { AgentsMetadataService } from '../../services/agents-metadata.service';
import { LmsFormsService } from '../../services/lms-forms.service';
import {
  AgentMetadata,
  FormActionRef,
  ReportRowsResponse,
} from '../../models/agent-metadata.model';

@Component({
  selector: 'app-chat-container',
  imports: [
    CommonModule,
    ChatInputComponent,
    ChatHeaderComponent,
    RouterOutlet,
    SvgIconComponent,
    OnboardingCardComponent,
    ReportBuilderPanelComponent,
  ],
  templateUrl: './chat-container.component.html',
  styleUrls: ['./chat-container.component.scss'],
})
export class ChatContainerComponent implements OnInit {

  chatStore = inject(ChatStore);
  authService = inject(AuthService<AuthUser>);
  private readonly agentsMeta = inject(AgentsMetadataService);
  private readonly lmsForms = inject(LmsFormsService);

  authUser = this.authService.user;
  homePrompts: HomePromptDTO[] = [];

  /** Slide-in panel visibility. */
  readonly reportPanelOpen = signal(false);

  /** Resolved agent metadata for the current selected agent (or null). */
  readonly selectedAgent = computed<AgentMetadata | null>(() => {
    const name = this.chatStore.selectedAgent();
    return this.agentsMeta.byName(name) ?? null;
  });

  /** All enabled agents (used by the generic empty-state tile grid). */
  readonly availableAgents = this.agentsMeta.agents;

  constructor() {
    this.loadHomePrompts();
  }

  ngOnInit(): void {
    void this.agentsMeta.load();
  }

  loadHomePrompts() {
    this.homePrompts = [
      {
        id: 1,
        title: 'What is the internal transfer process',
        prompt: 'What is the internal transfer process?',
        serviceName: 'Talent',
      },
      {
        id: 2,
        title: 'What is MENA Pursuit process',
        prompt: 'What is MENA Pursuit process',
        serviceName: 'C&I',
      },
      {
        id: 3,
        title: 'Where can I access the GCO templates?',
        prompt: 'Where can I access the GCO templates?',
        serviceName: 'GCO',
      },
      {
        id: 4,
        title: 'How do I submit  a BRIDGE request?',
        prompt: 'How do I submit  a BRIDGE request?',
        serviceName: 'Risk Management',
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

  // ── Onboarding card handlers ──

  onOnboardingPrompt(p: string): void {
    void this.chatStore.sendMessage(p);
  }

  onOpenReportBuilder(): void {
    if (this.selectedAgent()?.report_builder) {
      this.reportPanelOpen.set(true);
    }
  }

  closeReportPanel(): void {
    this.reportPanelOpen.set(false);
  }

  /** Report build returned rows — append a synthetic assistant message + post a NL user msg. */
  onReportBuilt(payload: { response: ReportRowsResponse; summary: string }): void {
    const agent = this.selectedAgent();
    void this.chatStore.sendMessage(`${agent?.display_name ?? 'Report'}: ${payload.summary}`);
    this.chatStore.appendSyntheticAssistantMessage({
      content: payload.response.summary || `Here are the rows for: ${payload.summary}`,
      reportRows: payload.response.rows ?? [],
      reportColumns: payload.response.columns,
      reportSummary: payload.response.summary,
    });
  }

  /** Transactional quick action — fetch the form schema and render it. */
  async onFormAction(action: FormActionRef): Promise<void> {
    try {
      const schema = await firstValueFrom(this.lmsForms.getSchema(action.name));
      this.chatStore.appendLmsFormMessage(schema);
    } catch (err) {
      console.error('Failed to load LMS form schema', err);
    }
  }

  /** Generic empty-state tile click — switch the active agent. */
  onAgentTile(agent: AgentMetadata): void {
    this.chatStore.selectedAgent.set(agent.name);
  }
}
