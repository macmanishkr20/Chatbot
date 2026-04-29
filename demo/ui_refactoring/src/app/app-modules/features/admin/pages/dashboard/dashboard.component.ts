import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ChartDataset } from 'chart.js';
import { AdminService } from '../../services/admin.service';
import { DashboardData, DashboardSummaryItem, DashboardVM, MonthEntry } from '../../models/dash-board';
import { FeedbackRating } from '../../../../../_shared/constants/feedback-rating';
import { PieChartComponent } from '../../../../controls/charts/pie-chart/pie-chart.component';
import { BarChartComponent } from '../../../../controls/charts/bar-chart/bar-chart.component';
import { FeedbackGridComponent } from './feedback-grid/feedback-grid.component';
import { CHART_COLORS } from '../../../../../_shared/constants/chart-colors';
import { ChartLables, ChartTypes } from '../../../../../_shared/constants/chart';


@Component({
  selector: 'app-dashboard',
  imports: [PieChartComponent, BarChartComponent, FeedbackGridComponent],
  templateUrl: './dashboard.component.html',
  styleUrls: ['./dashboard.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class DashboardComponent {
  private readonly adminService = inject(AdminService);
  private readonly destroyRef = inject(DestroyRef);

  readonly dashBoardSummary = signal<DashboardSummaryItem[] | null>(null);
  readonly dashBoardData = signal<DashboardData | null>(null);

  readonly pieLabels: string[] = [ChartLables.Helpful, ChartLables.NotHelpful];
  readonly pieColors: string[] = [CHART_COLORS.helpful, CHART_COLORS.notHelpful];

  readonly pieData = computed<number[]>(() => {
    const items = this.dashBoardData()?.feedbackByCategory ?? [];
    const positive = items.find((f) => f.rating === FeedbackRating.Positive)?.totalCount ?? 0;
    const negative = items.find((f) => f.rating === FeedbackRating.Negative)?.totalCount ?? 0;
    return [positive, negative];
  });

  private readonly barChartModel = computed(() =>
    this.buildBarChartModel(this.dashBoardData()?.feedbackByMonth ?? [])
  );

  readonly barLabels = computed(() => this.barChartModel().labels);
  readonly barDatasets = computed(() => this.barChartModel().datasets);

  readonly feedbackRows = computed(() => this.dashBoardData()?.messageFeedbacks ?? []);

  constructor() {
    this.loadDashboardSummary();
    this.loadDashboardData();
  }

  private loadDashboardSummary(): void {
    this.adminService
      .getDashboardSummary()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (data) => {
          if (data.success) {
            this.dashBoardSummary.set(data.result ?? null);
          }
        },
        error: () => {},
      });
  }

  private loadDashboardData(): void {
    this.adminService
      .getDashboardData()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (data) => {
          if (data.success) {
            this.dashBoardData.set(data.result ?? null);
          }
        },
        error: () => {},
      });
  }

  private buildBarChartModel(items: DashboardVM[]): {
    labels: string[];
    datasets: ChartDataset<ChartTypes.Bar>[];
  } {
    const uniqueMonths = this.extractSortedMonths(items);
    const labels = uniqueMonths.map((m) => m.label);

    const getCount = (month: MonthEntry, rating: FeedbackRating): number =>
      items.find(
        (f) => f.monthName === month.fullMonthName && f.year === month.year 
              && f.rating === rating
      )?.totalCount ?? 0;

    return {
      labels,
      datasets: [
        {
          label: ChartLables.Helpful,
          data: uniqueMonths.map((m) => getCount(m, FeedbackRating.Positive)),
          backgroundColor: CHART_COLORS.helpfulAlpha,
          borderColor: CHART_COLORS.helpful,
          borderWidth: 1,
          borderRadius: 4,
          hoverBackgroundColor: CHART_COLORS.helpfulHover,
          barThickness: 16,
        },
        {
          label: ChartLables.NotHelpful,
          data: uniqueMonths.map((m) => getCount(m, FeedbackRating.Negative)),
          backgroundColor: CHART_COLORS.notHelpfulAlpha,
          borderColor: CHART_COLORS.notHelpful,
          borderWidth: 1,
          borderRadius: 4,
          hoverBackgroundColor: CHART_COLORS.notHelpfulHover,
          barThickness: 16,
        },
      ],
    };
  }

  private extractSortedMonths(items: DashboardVM[]): MonthEntry[] {
    const seen = new Set<string>();
    const months: MonthEntry[] = [];

    for (const item of items) {
      const key = `${item.year}-${item.monthName}`;
      if (!seen.has(key)) {
        seen.add(key);
        const shortMonth = item.monthName?.substring(0, 3) ?? '';
        const shortYear = item.year ? String(item.year).slice(-2) : '';
        months.push({
          label: `${shortMonth} '${shortYear}`,
          fullMonthName: item.monthName,
          year: item.year,
          monthId: item.monthId,
        });
      }
    }

    return months.sort((a, b) =>
      a.year !== b.year ? a.year - b.year : (a.monthId ?? 0) - (b.monthId ?? 0)
    );
  }
}

