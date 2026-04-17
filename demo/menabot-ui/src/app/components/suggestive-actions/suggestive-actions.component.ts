import { Component, ChangeDetectionStrategy, input, output } from '@angular/core';
import { CommonModule } from '@angular/common';
import { SuggestiveAction } from '../../models/chat.models';

@Component({
  selector: 'app-suggestive-actions',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './suggestive-actions.component.html',
  styleUrl: './suggestive-actions.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class SuggestiveActionsComponent {
  /** Actions returned by the Supervisor agent. */
  actions = input.required<SuggestiveAction[]>();

  /** Emitted when the user clicks an action chip. */
  actionClicked = output<SuggestiveAction>();

  onAction(action: SuggestiveAction): void {
    this.actionClicked.emit(action);
  }

  trackByTitle(_: number, action: SuggestiveAction): string {
    return action.short_title;
  }
}
