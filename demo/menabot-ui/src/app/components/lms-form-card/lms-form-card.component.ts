import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, inject, input, output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { FormField, FormSchema, FormSubmitResult } from '../../models/agent-metadata.model';
import { LmsFormsService } from '../../services/lms-forms.service';

/**
 * Renders an adaptive LMS form (apply leave, etc.) driven by a FormSchema
 * emitted by the SSE `lms_form` event or fetched from
 * `GET /api/lms/forms/{action}`. Performs client-side required-field
 * validation and posts to `POST /api/lms/forms/{action}` on submit.
 */
@Component({
  selector: 'app-lms-form-card',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './lms-form-card.component.html',
  styleUrl: './lms-form-card.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class LmsFormCardComponent {
  private readonly lmsForms = inject(LmsFormsService);

  schema = input.required<FormSchema>();
  result = input<FormSubmitResult | null | undefined>(null);

  submitted = output<FormSubmitResult>();

  readonly values = signal<Record<string, unknown>>({});
  readonly missing = signal<Set<string>>(new Set());
  readonly submitting = signal(false);
  readonly errorMsg = signal<string | null>(null);

  readonly disabled = computed(() => !!this.result() || this.submitting());

  setValue(field: FormField, value: unknown): void {
    this.values.update((v) => ({ ...v, [field.name]: value }));
    if (this.missing().has(field.name)) {
      this.missing.update((s) => {
        const next = new Set(s);
        next.delete(field.name);
        return next;
      });
    }
  }

  isMissing(name: string): boolean {
    return this.missing().has(name);
  }

  onInput(field: FormField, event: Event): void {
    const target = event.target as HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement;
    let raw: unknown = target.value;
    if (field.type === 'number') {
      raw = target.value === '' ? null : Number(target.value);
    } else if (field.type === 'boolean') {
      raw = (target as HTMLInputElement).checked;
    }
    this.setValue(field, raw);
  }

  async onSubmit(): Promise<void> {
    if (this.disabled()) return;

    const missingNames = new Set<string>();
    for (const f of this.schema().fields) {
      if (!f.required) continue;
      const v = this.values()[f.name];
      const empty =
        v === undefined ||
        v === null ||
        (typeof v === 'string' && v.trim() === '');
      if (empty) missingNames.add(f.name);
    }
    if (missingNames.size > 0) {
      this.missing.set(missingNames);
      this.errorMsg.set('Please fill in the highlighted fields.');
      return;
    }

    this.submitting.set(true);
    this.errorMsg.set(null);
    try {
      const res = await new Promise<FormSubmitResult>((resolve, reject) => {
        this.lmsForms.submit(this.schema().action, this.values()).subscribe({
          next: resolve,
          error: reject,
        });
      });
      this.submitted.emit(res);
    } catch (err) {
      console.error('LMS form submit failed', err);
      this.errorMsg.set('Submission failed. Please try again.');
    } finally {
      this.submitting.set(false);
    }
  }
}
