import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { flatMap, map, mergeMap, Observable, of } from 'rxjs';
import { ServiceResult } from '../../../../_shared/models/service-result';
import { environment } from '../../../../../environments/environment';
import { Role } from './models/role';
import { UserModel } from './models/user-model';
import { UserInfoVM, UserVM } from '../../../models/user';

@Injectable({
  providedIn: 'root',
})
export class DataService {
  private readonly roleUrl = `${environment.apiUrl}auth/role`;
  private readonly userUrl = `${environment.apiUrl}api/register`;
  private readonly meUrl = `${environment.apiUrl}api/me`;

  constructor(private http: HttpClient) {}

  roles(): Observable<ServiceResult<Role[]>> {
    return this.http.get<ServiceResult<Role[]>>(`${this.roleUrl}`);
  }

  users(): Observable<ServiceResult<UserModel[]>> {
    return this.http.get<ServiceResult<UserModel[]>>(`${this.userUrl}/users`);
  }

  addUser(user: any): Observable<ServiceResult<UserModel>> {
    const roleId = user?.role?.id;
    const usrModel = new UserVM();
    usrModel.username = user.userName;
    usrModel.email = user.email;
    usrModel.role = roleId;
    usrModel.firstName = user.firstName;
    usrModel.lastName = user.lastName;
    usrModel.id = user?.userId ?? '';

    return this.http.post<ServiceResult<UserModel>>(`${this.userUrl}/${roleId}/role`, usrModel).pipe(
      mergeMap(result => {
        if (!result.success) {
          return of(result);
        }

        const usrInfo = new UserInfoVM();
        usrInfo.firstName = user.firstName;
        usrInfo.lastName = user.lastName;
        usrInfo.email = user.email;
        usrInfo.userId = result.result?.id ?? '';
        usrInfo.role = user.role.name;
        user.userId = result.result?.id;

        return this.http.post<ServiceResult<UserModel>>(`${this.meUrl}/create`, usrInfo).pipe(
          map(me => ({
            ...result,
            errors: me.errors,
            hasErrors: me.hasErrors,
            success: me.success,
            result: user
          }))
        );
      })
    );
  }

  editUser(user: any): Observable<void> {
        return this.http.post<void>(`${this.meUrl}/create`, user);
    }

    deleteUser(userId: string): Observable<void> {
        return this.http.post<void>(`${this.meUrl}/${userId}/delete`, {});
    }
  
  searchUser(email: string) {
        if (!email) {
            return of([]);
        }
        return this.http.get<any>(
            `https://graph.microsoft.com/v1.0/users?$filter=startswith(mail,'${email}')&$top=8`)
            .pipe(map(p => p.value.map((p1: any) => this.MapUser(p1))));
    }

    private MapUser(v: any) {
        return { mail: v.mail, userPrincipalName: v.userPrincipalName };
    }
}
