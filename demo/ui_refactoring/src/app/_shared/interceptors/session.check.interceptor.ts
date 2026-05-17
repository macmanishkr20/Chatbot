import { HttpInterceptorFn } from '@angular/common/http';
import { AuthUser } from '../messaging-service/auth-user';
import { AuthService } from '../messaging-service/auth.service';
import { inject } from '@angular/core';
import { catchError, throwError } from 'rxjs';
import { NgbModal } from '@ng-bootstrap/ng-bootstrap';
import { SessionTimeoutComponent } from '../components/session-timeout/session-timeout.component';

export const sessionCheckInterceptor: HttpInterceptorFn = (req, next) => {
  const authService = inject(AuthService<AuthUser>);
  const modalService = inject(NgbModal);
  const sessionId = authService.user.sessionId;

  if (sessionId) {
    const authReq = req.clone({
      headers: req.headers.set('SessionId', sessionId)
    });
    return next(authReq).pipe(catchError((err) => {
      if (err.status === 423) {
        modalService.open(SessionTimeoutComponent,
          { ariaLabelledBy: 'modal-basic-title', backdrop: 'static' });
      }
      return throwError(() => err);
    }));
  }
  return next(req);
};
