import { Injectable } from '@angular/core';
import { BehaviorSubject } from 'rxjs';
import { distinctUntilChanged, map } from 'rxjs/operators';

export class LoadState {
  loading = false;
}

@Injectable({
  providedIn: 'root',
})
export class LoadingService {
  private activeRequests = 0;
  private loadingSubject = new BehaviorSubject<boolean>(false);

  /** Emits only on actual boolean change — prevents redundant CD cycles */
  public loading$ = this.loadingSubject.asObservable().pipe(distinctUntilChanged());

  constructor() {}

  show() {
    this.activeRequests++;
    if (this.activeRequests === 1) {
      this.loadingSubject.next(true);
      document.getElementById('app-after-login')?.classList.add('loading');
    }
  }

  hide() {
    if (this.activeRequests > 0) {
      this.activeRequests--;
    }
    if (this.activeRequests === 0) {
      this.loadingSubject.next(false);
      document.getElementById('app-after-login')?.classList.remove('loading');
    }
  }

  /** Force-reset — safety valve for error recovery */
  reset() {
    this.activeRequests = 0;
    this.loadingSubject.next(false);
    document.getElementById('app-after-login')?.classList.remove('loading');
  }
}
