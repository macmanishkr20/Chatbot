import {
  Component,
  ChangeDetectionStrategy,
  inject,
  computed,
  ElementRef,
  ViewChild,
  AfterViewInit,
  effect,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { ChatService } from '../../services/chat.service';
import { AuthService } from '../../services/auth.service';
import { ThemeService } from '../../services/theme.service';
import { MessageBubbleComponent } from '../message-bubble/message-bubble.component';
import { ChatInputComponent } from '../chat-input/chat-input.component';
import { ExportMenuComponent } from '../export-menu/export-menu.component';
import { FunctionChipsComponent } from '../function-chips/function-chips.component';
import { MapBackdropComponent } from '../map-backdrop/map-backdrop.component';
import { SuggestiveAction } from '../../models/chat.models';
import { OnboardingCardComponent } from '../onboarding-card/onboarding-card.component';
import { ReportBuilderPanelComponent } from '../report-builder-panel/report-builder-panel.component';
import { AgentsMetadataService } from '../../services/agents-metadata.service';
import { LmsFormsService } from '../../services/lms-forms.service';
import { AgentMetadata, FormActionRef, ReportRowsResponse } from '../../models/agent-metadata.model';

@Component({
  selector: 'app-chat-window',
  standalone: true,
  imports: [
    CommonModule,
    MessageBubbleComponent,
    ChatInputComponent,
    ExportMenuComponent,
    FunctionChipsComponent,
    MapBackdropComponent,
    OnboardingCardComponent,
    ReportBuilderPanelComponent,
  ],
  templateUrl: './chat-window.component.html',
  styleUrl: './chat-window.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ChatWindowComponent implements AfterViewInit {
  readonly chat = inject(ChatService);
  readonly auth = inject(AuthService);
  readonly theme = inject(ThemeService);
  readonly agentsMeta = inject(AgentsMetadataService);
  private readonly lmsForms = inject(LmsFormsService);

  /** The currently selected agent's full metadata (or null). */
  readonly currentAgent = computed<AgentMetadata | null>(() => {
    const name = this.chat.selectedAgent();
    return this.agentsMeta.byName(name) ?? null;
  });

  @ViewChild('scrollContainer') scrollContainer!: ElementRef<HTMLDivElement>;

  /** Derive the title to show in the header. */
  readonly headerTitle = computed(() =>
    this.chat.conversationTitle() || 'New Conversation'
  );

  /** Find the last assistant message index for regenerate button. */
  readonly lastAssistantIdx = computed(() => {
    const msgs = this.chat.messages();
    for (let i = msgs.length - 1; i >= 0; i--) {
      if (msgs[i].role === 'assistant') return i;
    }
    return -1;
  });

  /** Whether to show the empty state (no messages). */
  readonly showEmpty = computed(() => this.chat.messages().length === 0);

  constructor() {
    // Auto-scroll when messages change
    effect(() => {
      this.chat.messages(); // track dependency
      this.scrollToBottom();
    });
    // Ensure the agent metadata is available for the onboarding card / launchers.
    void this.agentsMeta.load();
  }

  ngAfterViewInit(): void {
    this.scrollToBottom();
  }

  // ── Onboarding card handlers ──

  onPromptPicked(prompt: string): void {
    void this.chat.sendMessage(prompt);
  }

  onAgentTilePicked(agent: AgentMetadata): void {
    this.chat.startChatForAgent(agent.name);
  }

  onBuildReportClicked(): void {
    this.chat.reportPanelOpen.set(true);
  }

  onReportPanelClosed(): void {
    this.chat.reportPanelOpen.set(false);
  }

  onReportBuilt(payload: { response: ReportRowsResponse; summary: string }): void {
    const rows = payload.response.rows ?? [];
    const cols = payload.response.columns
      ?? (rows.length > 0 ? Object.keys(rows[0]) : []);
    // Synthetic user message describing the query.
    this.chat.appendSyntheticUserMessage(payload.summary);
    this.chat.appendSyntheticAssistantMessage({
      content: payload.response.summary || `Returned ${rows.length} rows.`,
      reportRows: rows,
      reportColumns: cols,
      reportSummary: payload.response.summary,
    });
  }

  onFormAction(fa: FormActionRef): void {
    this.lmsForms.getSchema(fa.name).subscribe({
      next: (schema) => this.chat.appendLmsFormMessage(schema),
      error: (err) => console.error('Failed to fetch LMS form schema', err),
    });
  }

  toggleSidebar(): void {
    this.chat.sidebarOpen.update(v => !v);
  }

  toggleTheme(): void {
    this.theme.toggle();
  }

  logout(): void {
    this.auth.logout();
  }

  onActionClicked(action: SuggestiveAction): void {
    this.chat.sendMessage(action.short_title);
  }

  sendStarter(text: string): void {
    this.chat.sendMessage(text);
  }

  trackById(_: number, msg: { id: string }): string {
    return msg.id;
  }

  private scrollRafId: number | null = null;

  private scrollToBottom(): void {
    // Coalesce rapid scroll requests into a single RAF
    if (this.scrollRafId !== null) return;
    this.scrollRafId = requestAnimationFrame(() => {
      this.scrollRafId = null;
      const el = this.scrollContainer?.nativeElement;
      if (el) {
        el.scrollTop = el.scrollHeight;
      }
    });
  }
}
