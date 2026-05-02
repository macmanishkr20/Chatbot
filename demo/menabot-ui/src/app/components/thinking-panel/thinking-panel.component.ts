import { Component, ChangeDetectionStrategy, input, effect, signal, computed, OnDestroy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ThinkingStep, StepGroup } from '../../models/chat.models';

/** Metadata for each step group — labels, icons, completion summaries. */
const GROUP_META: Record<string, { label: string; icon: string; summary: string }> = {
  preparation:   { label: 'Preparing',            icon: 'inventory_2',    summary: 'Loaded context' },
  understanding: { label: 'Understanding query',   icon: 'lightbulb',      summary: 'Query analyzed' },
  retrieval:     { label: 'Searching knowledge',   icon: 'travel_explore', summary: 'Found relevant sources' },
  quality:       { label: 'Evaluating quality',    icon: 'verified',       summary: 'Quality verified' },
  response:      { label: 'Generating answer',     icon: 'smart_toy',      summary: 'Response ready' },
};

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
  readonly rotatingLabel = signal('Looking into it…');

  /** Interval handle for rotating phrases. */
  private rotateInterval: ReturnType<typeof setInterval> | null = null;

  /** Track collapsed state per group key (user overrides). */
  private readonly groupCollapseOverrides = signal<Map<string, boolean>>(new Map());

  /** Build hierarchical step groups from flat steps. */
  readonly stepGroups = computed<StepGroup[]>(() => {
    const steps = this.steps();
    const overrides = this.groupCollapseOverrides();
    const groupMap = new Map<string, StepGroup>();

    for (const step of steps) {
      const key = step.group || 'other';
      if (!groupMap.has(key)) {
        const meta = GROUP_META[key] || { label: key, icon: 'settings', summary: 'Done' };
        groupMap.set(key, {
          key,
          label: meta.label,
          icon: meta.icon,
          summary: meta.summary,
          steps: [],
          state: 'pending',
          collapsed: false,
        });
      }
      const g = groupMap.get(key)!;
      g.steps.push(step);
    }

    // Determine group state and collapsed
    for (const g of groupMap.values()) {
      const hasRunning = g.steps.some(s => s.state === 'running');
      const allDone = g.steps.every(s => s.state === 'done');

      if (hasRunning) {
        g.state = 'running';
      } else if (allDone) {
        g.state = 'done';
      }

      // Apply user override if exists, otherwise auto-collapse completed groups
      const override = overrides.get(g.key);
      if (override !== undefined) {
        g.collapsed = override;
      } else {
        g.collapsed = g.state === 'done';
      }
    }

    return [...groupMap.values()];
  });

  constructor() {
    // Auto-collapse panel when all steps complete; rotate the label while running.
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

  /** Effective collapsed state for the whole panel. */
  isCollapsed(): boolean {
    return this.localCollapsed !== null ? this.localCollapsed : this.collapsed();
  }

  /** Whether all steps are completed. */
  allDone(): boolean {
    const s = this.steps();
    return s.length > 0 && s.every(step => step.state === 'done');
  }

  toggle(): void {
    this.localCollapsed = !this.isCollapsed();
  }

  /** Toggle a group's collapsed state. */
  toggleGroup(group: StepGroup): void {
    const newState = !group.collapsed;
    const current = this.groupCollapseOverrides();
    const updated = new Map(current);
    updated.set(group.key, newState);
    this.groupCollapseOverrides.set(updated);
  }

  trackByKey(_: number, group: StepGroup): string {
    return group.key;
  }

  trackByNode(_: number, step: ThinkingStep): string {
    return step.node;
  }

  private startRotation(): void {
    this.phraseIndex = 0;
    this.rotatingLabel.set(this.thinkingPhrases[0]);
    this.rotateInterval = setInterval(() => {
      this.phraseIndex = (this.phraseIndex + 1) % this.thinkingPhrases.length;
      this.rotatingLabel.set(this.thinkingPhrases[this.phraseIndex]);
    }, 5000);
  }

  private stopRotation(): void {
    if (this.rotateInterval) {
      clearInterval(this.rotateInterval);
      this.rotateInterval = null;
    }
  }
}
