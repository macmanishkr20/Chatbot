import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';
import { ClarificationCard, PromptOption } from '../../models/agent-metadata.model';

/**
 * Renders a clarification question card emitted by the agent via the SSE
 * `clarification` event. Options surface as clickable chips that re-submit
 * the chosen prompt.
 */
@Component({
  selector: 'app-clarification-card',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './clarification-card.component.html',
  styleUrl: './clarification-card.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ClarificationCardComponent {
  card = input.required<ClarificationCard>();
  picked = output<PromptOption>();

  onClick(opt: PromptOption): void {
    this.picked.emit(opt);
  }
}
