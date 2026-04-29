import { Injectable, inject } from '@angular/core';
import {
  HttpInterceptor,
  HttpRequest,
  HttpHandler,
  HttpEvent,
} from '@angular/common/http';
import { Observable } from 'rxjs';
import { finalize } from 'rxjs/operators';
import { LoadingService } from '../messaging-service/loading.service';

/**
 * URL segments that should NOT trigger the global loader.
 * These endpoints either manage their own loading UI or are high-frequency
 * background calls where a top-bar loader would be distracting.
 */
const SKIP_LOADER_PATTERNS: ReadonlyArray<RegExp> = [
  /\/api\/chat\//i,           // chat message posting & retrieval
  /\/api\/conversation\//i,   // conversation list (sidebar handles its own state)
  /\/api\/feedback\//i,       // feedback submission
];

@Injectable()
export class LoaderInterceptor implements HttpInterceptor {
  private readonly loadingService = inject(LoadingService);

  intercept<T>(
    req: HttpRequest<T>,
    next: HttpHandler,
  ): Observable<HttpEvent<T>> {
    if (this.shouldSkip(req.url)) {
      return next.handle(req);
    }

    this.loadingService.show();

    return next.handle(req).pipe(
      finalize(() => this.loadingService.hide()),
    );
  }

  private shouldSkip(url: string): boolean {
    return SKIP_LOADER_PATTERNS.some((pattern) => pattern.test(url));
  }
}
