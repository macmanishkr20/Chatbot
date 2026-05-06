import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { environment } from '../environments/environment';
import { FormSchema, FormSubmitResult } from '../models/agent-metadata.model';

/**
 * GET / POST `/api/lms/forms/{action}`.
 *  - GET  → returns a FormSchema describing the fields to render.
 *  - POST → submits the user's filled values and returns ok/message/request_id.
 */
@Injectable({ providedIn: 'root' })
export class LmsFormsService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiBaseUrl}/api/lms/forms`;

  getSchema(action: string): Observable<FormSchema> {
    return this.http.get<FormSchema>(`${this.base}/${encodeURIComponent(action)}`);
  }

  submit(action: string, payload: Record<string, unknown>): Observable<FormSubmitResult> {
    return this.http.post<FormSubmitResult>(
      `${this.base}/${encodeURIComponent(action)}`,
      payload,
    );
  }
}
