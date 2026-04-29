import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import { BaseChartDirective } from 'ng2-charts';
import { ChartData, ChartDataset, ChartOptions } from 'chart.js';
import { ChartTypes } from '../../../../_shared/constants/chart';

@Component({
  selector: 'app-bar-chart',
  imports: [BaseChartDirective],
  templateUrl: './bar-chart.component.html',
  styleUrl: './bar-chart.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class BarChartComponent {
  readonly chartTypes = ChartTypes;
  readonly labels = input.required<string[]>();
  readonly datasets = input.required<ChartDataset<ChartTypes.Bar>[]>();
  readonly title = input<string>('');

  readonly chartData = computed<ChartData<ChartTypes.Bar>>(() => ({
    labels: this.labels(),
    datasets: this.datasets(),
  }));

  readonly chartOptions: ChartOptions<ChartTypes.Bar> = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: {
        position: 'top',
        labels: {
          color: '#e0e0e0',
          padding: 16,
          font: { size: 12 },
          usePointStyle: true,
          pointStyle: 'circle',
          boxWidth: 6,
          boxHeight: 6,
        },
      },
      tooltip: {
        backgroundColor: 'rgba(15, 15, 28, 0.95)',
        titleColor: '#ffffff',
        bodyColor: '#cccccc',
        borderColor: 'rgba(255,255,255,0.12)',
        borderWidth: 1,
        padding: 12,
      },
    },
    scales: {
      x: {
        ticks: {
          color: '#9e9e9e',
          font: { size: 11 },
          maxRotation: 45,
          minRotation: 0,
          autoSkip: false,
        },
        grid: { display: false },
      },
      y: {
        beginAtZero: true,
        ticks: { display: false },
        grid: { display: false },
      },
    },
  };
}
