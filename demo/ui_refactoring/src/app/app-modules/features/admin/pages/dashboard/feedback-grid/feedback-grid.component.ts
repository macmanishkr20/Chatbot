import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  inject,
  input,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { DatePipe, SlicePipe } from '@angular/common';
import { NgbPaginationModule, NgbTooltipModule } from '@ng-bootstrap/ng-bootstrap';
import { AdminService } from '../../../services/admin.service';
import { FeedbackGridVM } from '../../../models/dash-board';
import { FeedbackRating, getRatingLabel } from '../../../../../../_shared/constants/feedback-rating';
import { DownloadService } from '../../../../../../_shared/_service/download.service';


@Component({
  selector: 'app-feedback-grid',
  imports: [DatePipe, SlicePipe, NgbPaginationModule, NgbTooltipModule],
  templateUrl: './feedback-grid.component.html',
  styleUrl: './feedback-grid.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class FeedbackGridComponent {
  readonly feedbacks = input<FeedbackGridVM[]>([]);
  readonly isExporting = signal(false);

  page = 1;
  pageSize = 5;

  private readonly adminService = inject(AdminService);
  private readonly downloadService = inject(DownloadService);
  private readonly destroyRef = inject(DestroyRef);

  getLabel(rating: FeedbackRating): string {
    return getRatingLabel(rating);
  }


  exportExcel(): void {
    if (this.isExporting()) {
      return;
    }
    this.isExporting.set(true);

    this.adminService
      .exportFeedbackExcel()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (response) => {
          this.downloadService.saveFile(response, `Feedbacks.xlsx`);
          this.isExporting.set(false);
        },
        error: () => {
          this.isExporting.set(false);
        },
      });
  }
}
