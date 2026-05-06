import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, OnInit, inject } from '@angular/core';
import { AgentsMetadataService } from '../../services/agents-metadata.service';
import { ChatStore } from '../../services/chat.store';
import { AgentMetadata } from '../../models/agent-metadata.model';

/**
 * Sidebar "Quick start" launcher list. Renders one row per enabled agent
 * (icon + display name). Clicking a row opens a fresh chat seeded with that
 * agent's module context.
 *
 * Failure to load metadata is silent — the launcher simply hides itself.
 */
@Component({
  selector: 'app-module-launcher',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './module-launcher.component.html',
  styleUrl: './module-launcher.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ModuleLauncherComponent implements OnInit {
  private readonly agentsMeta = inject(AgentsMetadataService);
  private readonly chatStore = inject(ChatStore);

  readonly agents = this.agentsMeta.agents;

  ngOnInit(): void {
    void this.agentsMeta.load();
  }

  onPick(agent: AgentMetadata): void {
    this.chatStore.startChatForAgent(agent.name);
  }
}
