import { ChangeDetectorRef, Component, NgZone, OnDestroy } from '@angular/core';
import { Subscription } from 'rxjs';
import { LoadingService } from '../../messaging-service/loading.service';


@Component({
  selector: 'app-loader',
  imports: [],
  templateUrl: './loader.component.html',
  styleUrls: ['./loader.component.scss'],
})
export class LoaderComponent implements OnDestroy {
  isLoading = false;
  loadingSubscription: Subscription | undefined;

  constructor(
    private loadingService: LoadingService,
    private cdRef: ChangeDetectorRef,
    private zone: NgZone
  ) {
    this.loadingSubscription = this.loadingService.loading$.subscribe(
      (isLoading) => {
        this.isLoading = isLoading;
        this.cdRef.markForCheck();
      }
    );
  }

  ngOnDestroy() {
    if (this.loadingSubscription) {
      this.loadingSubscription.unsubscribe();
    }
  }
}
