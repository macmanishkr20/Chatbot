import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import { BaseChartDirective } from 'ng2-charts';
import { ChartData, ChartOptions } from 'chart.js';
import { ChartTypes } from '../../../../_shared/constants/chart';

@Component({
  selector: 'app-pie-chart',
  imports: [BaseChartDirective],
  templateUrl: './pie-chart.component.html',
  styleUrl: './pie-chart.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class PieChartComponent {
  readonly chartTypes = ChartTypes;
  readonly labels = input.required<string[]>();
  readonly data = input.required<number[]>();
  readonly backgroundColors = input.required<string[]>();
  readonly title = input<string>('');

  readonly hasData = computed(() => this.data().some((v) => v > 0));

  readonly chartData = computed<ChartData<ChartTypes.Pie>>(() => ({
    labels: this.labels(),
    datasets: [
      {
        data: this.data(),
        backgroundColor: this.backgroundColors(),
        borderColor: '#1a1a2e',
        borderWidth: 3,
        hoverBorderColor: 'rgba(255,255,255,0.4)',
        hoverBorderWidth: 2,
      },
    ],
  }));

  readonly chartOptions: ChartOptions<ChartTypes.Pie> = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: {
        position: 'bottom',
        labels: {
          color: '#e0e0e0',
          padding: 20,
          font: { size: 12 },
          usePointStyle: true,
          pointStyle: 'circle',
          boxWidth: 8,
          boxHeight: 8,
        },
      },
      tooltip: {
        backgroundColor: 'rgba(15, 15, 28, 0.95)',
        titleColor: '#ffffff',
        bodyColor: '#cccccc',
        borderColor: 'rgba(255,255,255,0.12)',
        borderWidth: 1,
        padding: 12,
        callbacks: {
          label: (ctx) => {
            const value = ctx.raw as number;
            const total = (ctx.dataset.data as number[]).reduce((a, b) => a + b, 0);
            const pct = total > 0 ? Math.round((value / total) * 100) : 0;
            return `  ${ctx.label}: ${value} (${pct}%)`;
          },
        },
      },
    },
  };
}
