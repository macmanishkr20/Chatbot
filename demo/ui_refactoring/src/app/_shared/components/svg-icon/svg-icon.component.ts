import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
  input,
} from '@angular/core';
import { toObservable, toSignal } from '@angular/core/rxjs-interop';
import { DomSanitizer, SafeHtml } from '@angular/platform-browser';
import { switchMap } from 'rxjs';
import { IconService } from '../../_service/icon.service';

/**
 * Reusable SVG icon renderer.
 *
 * Looks up the icon markup from `assets/json/icons.json` (via `IconService`)
 * and renders it inline so it can be styled with CSS (size, color, etc.).
 *
 * Usage:
 *   <app-svg-icon name="download-file"></app-svg-icon>
 *   <app-svg-icon name="download-file" cssClass="icon-lg text-primary"></app-svg-icon>
 *   <app-svg-icon name="download-file" ariaLabel="Download file"></app-svg-icon>
 */
@Component({
  selector: 'app-svg-icon',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './svg-icon.component.html',
  styleUrls: ['./svg-icon.component.scss'],
})
export class SvgIconComponent {
  /** Icon name as defined in `assets/json/icons.json`. */
  readonly name = input.required<string>();

  /** Optional CSS class(es) applied to the wrapper element. */
  readonly cssClass = input<string>('');

  /** Optional accessible label. When provided, the icon is exposed as role="img". */
  readonly ariaLabel = input<string>('');

  private readonly sanitizer = inject(DomSanitizer);
  private readonly iconService = inject(IconService);

  private readonly markup = toSignal(
    toObservable(this.name).pipe(
      switchMap((n) => this.iconService.getIcon(n))
    ),
    { initialValue: '' }
  );

  protected readonly safeIcon = computed<SafeHtml>(() =>
    this.sanitizer.bypassSecurityTrustHtml(this.markup() ?? '')
  );
}
