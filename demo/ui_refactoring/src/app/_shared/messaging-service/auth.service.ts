import { Injectable } from '@angular/core';
import { AuthUser } from './auth-user';
import { Observable, BehaviorSubject, of } from 'rxjs';
import { NgxPermissionsService, NgxRolesService } from 'ngx-permissions';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { environment } from '../../../environments/environment';
import { ServiceResult } from '../models/service-result';

@Injectable({
  providedIn: 'root',
})
export class AuthService<T extends AuthUser> {
  private readonly tokenUrl = `${environment.apiUrl}token`;
  private readonly meUrl = `${environment.apiUrl}me`;

  private readonly authKey = 'auth_user';
  private subject = new BehaviorSubject<T>({} as T);

  constructor(
    private permisson: NgxPermissionsService,
    private role: NgxRolesService,
    private http: HttpClient
  ) {
    this.subject.next(this.user);
  }

  statusChanged(): Observable<T> {
    return this.subject.asObservable();
  }

  private hasKey(): boolean {
    const a = sessionStorage.getItem(this.authKey);
    return a !== null && a !== undefined;
  }

  set user(value: T) {
    if (this.hasKey()) {
      this.permisson.flushPermissions();
      this.role.flushRoles();
      sessionStorage.removeItem(this.authKey);
    }

    sessionStorage.setItem(this.authKey, btoa(JSON.stringify(value)));
    this.subject.next(value);
  }
  get user(): T {
    if (this.hasKey()) {
      const authData = sessionStorage.getItem(this.authKey);
      const us1 = authData ? <T>JSON.parse(atob(authData)) : ({} as T);

      const us = AuthUser.Clone(us1);
      const d = this.permisson.getPermissions();
      if (d) {
        const r = us.roles[0].value.toUpperCase();

        us.features.forEach((v1, i) => {
          this.permisson.addPermission(v1.value);
        });
        this.role.addRole(
          r,
          us.features.map((p) => p.value)
        );
      }

      return <T>us;
    }

    return {} as T;
  }

  aadPic(): Observable<Blob> {
    const httpOptions = {
      headers: new HttpHeaders({
        contentType: 'image/jpeg',
      }),
      responseType: 'blob' as 'json',
    };
    return this.http.get<Blob>(
      `https://graph.microsoft.com/v1.0/me/photo/$value`,
      httpOptions
    );
  }

  fetchAuthToken(token: string): Observable<TokenResult> {
    return this.http.post<TokenResult>(this.tokenUrl, `"${token}"`);
  }

  meInfo(userId: string, sessionId: string): Observable<ServiceResult<any>> {
    const httpOptions = {
      headers: new HttpHeaders({
        userId: userId,
        sessionId: sessionId,
      }),
    };
    return this.http.post<ServiceResult<any>>(
      this.meUrl,
      undefined,
      httpOptions
    );
  }

  fetchRefreshToken(): Observable<TokenResult> {
    // const a = {
    //   token: this.user.token,
    //   refreshToken: this.user.refreshToken,
    // };
    // return this.http.post<TokenResult>(`${this.tokenUrl}/refresh`, a);
    return of();
  }

  remove() {
    this.permisson.flushPermissions();
    this.role.flushRoles();
    sessionStorage.removeItem(this.authKey);

    // this.subject.next({} as T);
    // this.authService.logout();
  }

  removeAll() {
    // sessionStorage.clear();
    this.subject.next({} as T);
  }
}

export class TokenResult {
  token!: string;
  refreshToken!: string;
}
