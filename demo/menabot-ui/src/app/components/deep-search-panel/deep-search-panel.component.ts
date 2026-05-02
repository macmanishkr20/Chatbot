import { Component, ChangeDetectionStrategy, input } from '@angular/core';
import { CommonModule } from '@angular/common';
import { DeepSearchStep } from '../../models/chat.models';

@Component({
  selector: 'app-deep-search-panel',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './deep-search-panel.component.html',
  styleUrl: './deep-search-panel.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class DeepSearchPanelComponent {
  /** Status messages from the iterative multi-function search. */
  steps = input.required<DeepSearchStep[]>();

  /** Whether the panel starts collapsed. */
  collapsed = input(false);

  /** Whether the search is still running (streaming). */
  isSearching = input(false);

  /** Local override — null means "use the input". */
  private localCollapsed: boolean | null = null;

  /** Effective collapsed state. */
  get isCollapsed(): boolean {
    return this.localCollapsed !== null ? this.localCollapsed : this.collapsed();
  }

  /** Whether the deep search is complete (panel is collapsed and not searching). */
  get allDone(): boolean {
    return !this.isSearching() && this.steps().length > 0;
  }

  toggle(): void {
    this.localCollapsed = !this.isCollapsed;
  }
}
