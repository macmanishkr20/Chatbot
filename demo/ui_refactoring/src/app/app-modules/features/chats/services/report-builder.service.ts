import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { environment } from '../../../../../environments/environment';
import { QueryPlan, ReportRowsResponse } from '../models/agent-metadata.model';

/**
 * POST /api/reports/build — submits a structured report plan and returns
 * tabular rows + an optional NL summary.
 */
@Injectable({ providedIn: 'root' })
export class ReportBuilderService {
  private readonly http = inject(HttpClient);
  private readonly url = `${environment.apiUrl}api/reports/build`;

  build(agent: string, plan: QueryPlan): Observable<ReportRowsResponse> {
    return this.http.post<ReportRowsResponse>(this.url, { agent, plan });
  }
}
