import { Component, ChangeDetectionStrategy, input } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ThinkingStep } from '../../models/chat.model';

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

  /** Whether the panel starts collapsed. */
  collapsed = input(false);

  /** Local override — null means "use the input". */
  private localCollapsed: boolean | null = null;

  /** Effective collapsed state. */
  get isCollapsed(): boolean {
    return this.localCollapsed !== null ? this.localCollapsed : this.collapsed();
  }

  /** Whether all steps are completed. */
  get allDone(): boolean {
    const s = this.steps();
    return s.length > 0 && s.every(step => step.state === 'done');
  }

  toggle(): void {
    this.localCollapsed = !this.isCollapsed;
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
