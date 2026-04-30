import { Component, ChangeDetectionStrategy, input } from '@angular/core';
import { CommonModule } from '@angular/common';

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
  steps = input.required<string[]>();

  /** Whether the panel starts collapsed. */
  collapsed = input(false);

  /** Whether the search is still running. */
  isSearching = input(false);

  /** Local override — null means "use the input". */
  private localCollapsed: boolean | null = null;

  get isCollapsed(): boolean {
    return this.localCollapsed !== null ? this.localCollapsed : this.collapsed();
  }

  get allDone(): boolean {
    return !this.isSearching() && this.steps().length > 0;
  }

  toggle(): void {
    this.localCollapsed = !this.isCollapsed;
  }
}
