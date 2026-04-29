import { HttpClient, HttpResponse } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { environment } from '../../../../../environments/environment';
import { Observable } from 'rxjs';
import { ServiceResult } from '../../../../_shared/models/service-result';
import { DashboardData, DashboardSummaryItem } from '../models/dash-board';

@Injectable({
  providedIn: 'root',
})
export class AdminService {
  private readonly dashboardUrl = `${environment.apiUrl}api/dashboard`;
  
  private readonly httpClient = inject(HttpClient);

  getDashboardSummary(): Observable<ServiceResult<DashboardSummaryItem[]>> {
    return this.httpClient.get<ServiceResult<DashboardSummaryItem[]>>(this.dashboardUrl);
  }

  getDashboardData(): Observable<ServiceResult<DashboardData>> {
    return this.httpClient.get<ServiceResult<DashboardData>>(`${this.dashboardUrl}/getDashboardData`);
  }

  exportFeedbackExcel(): Observable<HttpResponse<Blob>> {
    return this.httpClient.get(`${this.dashboardUrl}/exportFeedback`, { responseType: 'blob', observe: 'response' });
  }
}
