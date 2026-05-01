import { Component, ChangeDetectionStrategy, input, effect, signal, OnDestroy } from '@angular/core';
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
export class ThinkingPanelComponent implements OnDestroy {
  /** The list of thinking steps to display. */
  steps = input.required<ThinkingStep[]>();

  /** Whether the panel starts collapsed. */
  collapsed = input(false);

  /** Local override — null means "use the input". */
  private localCollapsed: boolean | null = null;

  /** Track whether we've already auto-collapsed on completion. */
  private autoCollapsedOnDone = false;

  /** Rotating thinking phrases. */
  private readonly thinkingPhrases = [
    'Looking into it…',
    'Connecting the dots…',
    'Diving deeper…',
    'Piecing it together…',
    'Crafting your answer…',
    'Wrapping things up…',
  ];

  private phraseIndex = 0;

  /** Currently displayed thinking label (rotates while running). */
  readonly thinkingLabel = signal('Looking into it…');

  /** Interval handle for rotating phrases. */
  private rotateInterval: ReturnType<typeof setInterval> | null = null;

  constructor() {
    // Auto-collapse when all steps complete; rotate the label while running.
    effect(() => {
      const s = this.steps();
      const done = s.length > 0 && s.every(step => step.state === 'done');
      if (done && !this.autoCollapsedOnDone) {
        this.autoCollapsedOnDone = true;
        this.localCollapsed = true;
        this.stopRotation();
      } else if (!done && s.length > 0 && !this.rotateInterval) {
        this.startRotation();
      }
    });
  }

  ngOnDestroy(): void {
    this.stopRotation();
  }

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

  private startRotation(): void {
    this.phraseIndex = 0;
    this.thinkingLabel.set(this.thinkingPhrases[0]);
    this.rotateInterval = setInterval(() => {
      this.phraseIndex = (this.phraseIndex + 1) % this.thinkingPhrases.length;
      this.thinkingLabel.set(this.thinkingPhrases[this.phraseIndex]);
    }, 5000);
  }

  private stopRotation(): void {
    if (this.rotateInterval) {
      clearInterval(this.rotateInterval);
      this.rotateInterval = null;
    }
  }
}
