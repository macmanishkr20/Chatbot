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
  /** Pre-selected module (null = show generic launcher tiles). */
  agent = input<AgentMetadata | null>(null);
  /** Available agents — used by the generic empty-state to render tiles. */
  agents = input<AgentMetadata[]>([]);

  /** A user-prompt chip was clicked → host should send it as a user msg. */
  promptPicked = output<string>();
  /** A form action quick-button was clicked → host should fetch + render the form. */
  formAction = output<FormActionRef>();
  /** "Build a report" button clicked → host should open the panel. */
  buildReport = output<void>();
  /** A launcher tile (no agent yet) was clicked → host should switch to that agent. */
  agentPicked = output<AgentMetadata>();

  readonly previewPrompts = computed(() =>
    (this.agent()?.example_prompts ?? []).slice(0, 6),
  );

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
