import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable, of } from 'rxjs';
import { catchError, mergeMap } from 'rxjs/operators';
import { TokenResult, AuthService } from '../messaging-service/auth.service';
import { AuthUser, Claim } from '../messaging-service/auth-user';
import { environment } from '../../../environments/environment';
import { ServiceResult } from '../models/service-result';
import { MenuItem } from '../models/menu-item';

const readFile = (blob: Blob, reader: FileReader = new FileReader()) =>
  new Observable((obs) => {
    if (!(blob instanceof Blob)) {
      obs.error(new Error('`blob` must be an instance of File or Blob.'));
      return;
    }

    reader.onerror = (err) => obs.error(err);
    reader.onabort = (err) => obs.error(err);
    reader.onload = () => obs.next(reader.result);
    reader.onloadend = () => obs.complete();

    return reader.readAsDataURL(blob);
  });

@Injectable({
  providedIn: 'root',
})
export class LoginService {
  private readonly authUrl = `${environment.apiUrl}api/register`;

  constructor(
    private http: HttpClient,
    private authService: AuthService<AuthUser>
  ) {}

  // get isad(): boolean {
  //   return environment.isad;
  // }

  validate(): Observable<LoginResult> {
    return this.authService.aadPic().pipe(
      catchError((err) => {
        console.error(err);
        return of(new Blob());
      }),
      mergeMap((aadMe) => {
        return readFile(aadMe).pipe(
          catchError((err) => {
            console.error(err);
            return of(undefined);
          }),
          mergeMap((u) => {
            let blobPic = u as string | undefined;

            if (blobPic && blobPic.endsWith('data:')) {
              blobPic = undefined;
            }
            return this.fetchUserN().pipe(
              mergeMap((p) => {
                if (p.success) {
                  var result = p.result;

                  const a = new LoginResult();
                  a.succeeded = true;
                  a.id = result.id;
                  a.sessionId = result.sessionId;
                  a.email = result.email;
                  a.userId = result.userId;
                  a.firstName = result.firstName;
                  a.lastName = result.lastName;
                  a.profilePicUrl = blobPic;
                  a.claims = result.claims;
                  a.menus = result.userMenus;
                  a.userInfoId = result.userInfoId;
                  return of(a);
                } else {
                  return of(new LoginResult());
                }
              })
            );
          })
        );
      })
    );
  }
  private fetchUserN(): Observable<ServiceResult<any>> {
    return this.http.get<ServiceResult<any>>(`${this.authUrl}/validate`);
  }
  private fetchUser(blobPic: string | undefined): Observable<LoginResult> {
    return this.http.get<LoginResult>(`${this.authUrl}/validate`).pipe(
      mergeMap((validationResult) => {
        if (validationResult.succeeded) {
          return this.authService
            .meInfo(validationResult.id, validationResult.sessionId)
            .pipe(
              mergeMap((userInfo) => {
                if (userInfo.success) {
                  validationResult.firstName = userInfo.result.firstName;
                  validationResult.lastName = userInfo.result.lastName;
                  validationResult.userId = userInfo.result.id;
                  validationResult.profilePicUrl = blobPic;
                } else {
                  validationResult.succeeded = false;
                }

                return of(validationResult);
              })
            );
        } else {
          return of(validationResult);
        }
      })
    );
  }

  showPrivacyConsent(userId: number): Observable<boolean> {
    return this.http.get<boolean>(
      `${this.authUrl}/${userId}/showPrivacyConsent`
    );
  }

  createPrivacyConsent(userId: number): Observable<boolean> {
    return this.http.get<boolean>(
      `${this.authUrl}/${userId}/createPrivacyConsent`
    );
  }
}

export class LoginResult extends TokenResult {
  succeeded: boolean = false;
  isLockedOut: boolean = false;
  isNotAllowed: boolean = false;
  requiresTwoFactor: boolean = false;
  id: string = '';
  sessionId: string = '';
  email: string = '';
  userId: number = 0;
  firstName: string = '';
  lastName: string = '';
  profilePicUrl: string | undefined = undefined;
  claims: Claim[] = [];
  menus: MenuItem[] = [];
  userInfoId: number = 0;
}
