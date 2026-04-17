import { Component, ChangeDetectionStrategy, input } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ThinkingStep } from '../../models/chat.models';

@Component({
  selector: 'app-thinking-panel',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './thinking-panel.component.html',
  styleUrl: './thinking-panel.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ThinkingPanelComponent {
  /** The list of thinking steps to display. */
  steps = input.required<ThinkingStep[]>();

  /** Whether the panel is collapsed. */
  collapsed = input(false);

  /** Emitted when the user toggles collapsed state. */
  isCollapsed = false;

  toggle(): void {
    this.isCollapsed = !this.isCollapsed;
  }

  trackByNode(_: number, step: ThinkingStep): string {
    return step.node;
  }

  /** Friendly label for the step's node name. */
  formatNode(node: string): string {
    return node
      .replace(/_/g, ' ')
      .replace(/\b\w/g, c => c.toUpperCase());
  }
}
