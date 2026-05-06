import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, inject, input, output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import {
  AgentMetadata,
  QueryFilter,
  QueryPlan,
  ReportAggregation,
  ReportColumn,
  ReportRowsResponse,
} from '../../models/agent-metadata.model';
import { ReportBuilderService } from '../../services/report-builder.service';

/**
 * Right-side slide-in panel that translates an agent's `report_builder`
 * schema into a structured query plan, then submits it to
 * `POST /api/reports/build`.
 *
 * Driven entirely by the metadata schema — column types determine which
 * filter widget renders (string-with-values → multi-select, date → range
 * picker, number → between, boolean → toggle).
 */
@Component({
  selector: 'app-report-builder-panel',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './report-builder-panel.component.html',
  styleUrl: './report-builder-panel.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ReportBuilderPanelComponent {
  private readonly reportSvc = inject(ReportBuilderService);

  agent = input.required<AgentMetadata>();
  open = input<boolean>(false);
  closed = output<void>();
  /** Emitted with the result + the human-readable plan summary. */
  built = output<{ response: ReportRowsResponse; summary: string }>();

  // Selected column names (multi-select via chip toggle).
  readonly selectedColumns = signal<Set<string>>(new Set());

  // Per-column filter values keyed by column.name.
  readonly stringFilters = signal<Record<string, Set<string>>>({});
  readonly dateFilters = signal<Record<string, { start: string; end: string; preset?: string }>>({});
  readonly numberFilters = signal<Record<string, { lo: number | null; hi: number | null }>>({});
  readonly boolFilters = signal<Record<string, boolean | null>>({});

  readonly groupBy = signal<string>('');
  readonly aggregate = signal<ReportAggregation | ''>('');
  readonly aggregateColumn = signal<string>('');
  readonly sortColumn = signal<string>('');
  readonly sortDirection = signal<'asc' | 'desc'>('desc');
  readonly limit = signal<number>(100);
  readonly submitting = signal(false);
  readonly error = signal<string | null>(null);

  readonly columns = computed<ReportColumn[]>(() => this.agent().report_builder?.columns ?? []);
  readonly aggregations = computed<ReportAggregation[]>(
    () => this.agent().report_builder?.aggregations ?? ['sum', 'avg', 'count', 'min', 'max'],
  );
  readonly groupable = computed(() => this.columns().filter((c) => c.groupable));
  readonly aggregatable = computed(() => this.columns().filter((c) => c.aggregatable));
  readonly filterable = computed(() => this.columns().filter((c) => c.filterable));

  toggleColumn(name: string): void {
    this.selectedColumns.update((s) => {
      const next = new Set(s);
      if (next.has(name)) next.delete(name); else next.add(name);
      return next;
    });
  }

  isColSelected(name: string): boolean {
    return this.selectedColumns().has(name);
  }

  // ── String filter chip toggling ──
  toggleStringValue(col: string, val: string): void {
    this.stringFilters.update((map) => {
      const next = { ...map };
      const set = new Set(next[col] ?? []);
      if (set.has(val)) set.delete(val); else set.add(val);
      next[col] = set;
      return next;
    });
  }

  isStringSelected(col: string, val: string): boolean {
    return !!this.stringFilters()[col]?.has(val);
  }

  setDate(col: string, key: 'start' | 'end', value: string): void {
    this.dateFilters.update((m) => {
      const cur = m[col] ?? { start: '', end: '' };
      return { ...m, [col]: { ...cur, [key]: value, preset: undefined } };
    });
  }

  applyFyPreset(col: string, preset: 'fy_current' | 'fy_previous' | 'q1' | 'q2' | 'q3' | 'q4'): void {
    const now = new Date();
    const fyStartYear = now.getMonth() >= 3 ? now.getFullYear() : now.getFullYear() - 1;
    let start = new Date(fyStartYear, 3, 1);
    let end = new Date(fyStartYear + 1, 2, 31);
    if (preset === 'fy_previous') {
      start = new Date(fyStartYear - 1, 3, 1);
      end = new Date(fyStartYear, 2, 31);
    } else if (preset.startsWith('q')) {
      const q = Number(preset.slice(1));
      start = new Date(fyStartYear, 3 + (q - 1) * 3, 1);
      end = new Date(fyStartYear, 3 + q * 3, 0);
    }
    const fmt = (d: Date) => d.toISOString().slice(0, 10);
    this.dateFilters.update((m) => ({
      ...m,
      [col]: { start: fmt(start), end: fmt(end), preset },
    }));
  }

  setNumber(col: string, key: 'lo' | 'hi', raw: string): void {
    const n = raw === '' ? null : Number(raw);
    this.numberFilters.update((m) => {
      const cur = m[col] ?? { lo: null, hi: null };
      return { ...m, [col]: { ...cur, [key]: n } };
    });
  }

  setBool(col: string, value: boolean): void {
    this.boolFilters.update((m) => ({ ...m, [col]: value }));
  }

  clearBool(col: string): void {
    this.boolFilters.update((m) => {
      const next = { ...m };
      delete next[col];
      return next;
    });
  }

  buildPlan(): { plan: QueryPlan; summary: string } {
    const filters: QueryFilter[] = [];

    for (const [col, set] of Object.entries(this.stringFilters())) {
      if (set && set.size > 0) {
        filters.push({ column: col, op: 'in', values: [...set] });
      }
    }
    for (const [col, range] of Object.entries(this.dateFilters())) {
      if (range && (range.start || range.end)) {
        filters.push({
          column: col,
          op: 'between',
          start: range.start || undefined,
          end: range.end || undefined,
          fy_label: range.preset,
        });
      }
    }
    for (const [col, range] of Object.entries(this.numberFilters())) {
      if (range && (range.lo != null || range.hi != null)) {
        filters.push({ column: col, op: 'between', lo: range.lo ?? undefined, hi: range.hi ?? undefined });
      }
    }
    for (const [col, val] of Object.entries(this.boolFilters())) {
      if (val !== null && val !== undefined) {
        filters.push({ column: col, op: 'is', value: val });
      }
    }

    const groupBy = this.groupBy() ? [this.groupBy()] : [];
    const orderBy = this.sortColumn()
      ? [{ column: this.sortColumn(), direction: this.sortDirection() }]
      : [];

    const intent: QueryPlan['intent'] = this.aggregate() ? 'aggregate' : 'list';

    const plan: QueryPlan = {
      intent,
      aggregate: this.aggregate() || undefined,
      aggregate_column: this.aggregateColumn() || undefined,
      filters,
      group_by: groupBy,
      order_by: orderBy,
      limit: Number(this.limit()) || 100,
    };

    const parts: string[] = [];
    parts.push(intent === 'aggregate' ? `${this.aggregate()} of ${this.aggregateColumn() || 'rows'}` : 'List rows');
    if (groupBy.length) parts.push(`grouped by ${groupBy.join(', ')}`);
    if (filters.length) parts.push(`filtered by ${filters.map((f) => f.column).join(', ')}`);
    if (orderBy.length) parts.push(`sorted by ${orderBy[0].column} ${orderBy[0].direction}`);
    parts.push(`(limit ${plan.limit})`);
    const summary = parts.join(' ');

    return { plan, summary };
  }

  async onSubmit(): Promise<void> {
    if (this.submitting()) return;
    this.submitting.set(true);
    this.error.set(null);
    const { plan, summary } = this.buildPlan();
    try {
      const response = await new Promise<ReportRowsResponse>((resolve, reject) => {
        this.reportSvc.build(this.agent().name, plan).subscribe({ next: resolve, error: reject });
      });
      this.built.emit({ response, summary });
      this.closed.emit();
    } catch (err) {
      console.error('Report build failed', err);
      this.error.set('Could not build report. Please try again.');
    } finally {
      this.submitting.set(false);
    }
  }

  onClose(): void {
    this.closed.emit();
  }
}
