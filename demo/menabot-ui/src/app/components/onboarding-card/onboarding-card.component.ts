import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, input, output } from '@angular/core';
import { AgentMetadata, FormActionRef } from '../../models/agent-metadata.model';

/**
 * Welcome / onboarding card rendered at the top of a fresh chat.
 *
 * - Module description + 4-6 example_prompt chips.
 * - Analytical agents → "Build a report" button.
 * - Transactional agents → quick-action buttons per form_action.
 *
 * If `agent` is null, renders the generic empty-state with four big
 * launcher buttons sourced from `agents`.
 */
@Component({
  selector: 'app-onboarding-card',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './onboarding-card.component.html',
  styleUrl: './onboarding-card.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class OnboardingCardComponent {
  agent = input<AgentMetadata | null>(null);
  agents = input<AgentMetadata[]>([]);

  promptPicked = output<string>();
  formAction = output<FormActionRef>();
  buildReport = output<void>();
  agentPicked = output<AgentMetadata>();

  readonly previewPrompts = computed(() =>
    (this.agent()?.example_prompts ?? []).slice(0, 6),
  );

  readonly tiles = computed(() => this.agents().slice(0, 4));

  onChip(p: string): void {
    this.promptPicked.emit(p);
  }

  onFormAction(a: FormActionRef): void {
    this.formAction.emit(a);
  }

  onBuildReport(): void {
    this.buildReport.emit();
  }

  onAgentTile(a: AgentMetadata): void {
    this.agentPicked.emit(a);
  }
}
