import { HttpInterceptorFn } from '@angular/common/http';
import { AuthUser } from '../messaging-service/auth-user';
import { AuthService } from '../messaging-service/auth.service';
import { inject } from '@angular/core';
import { catchError, throwError } from 'rxjs';
import { NgbModal } from '@ng-bootstrap/ng-bootstrap';
import { SessionTimeoutComponent } from '../components/session-timeout/session-timeout.component';
import { Router } from '@angular/router';

export const sessionCheckInterceptor: HttpInterceptorFn = (req, next) => {
  const authService = inject(AuthService<AuthUser>);
  const modalService = inject(NgbModal);
  const router = inject(Router);
  const sessionId = authService.user.sessionId;

  if (sessionId) {
    const authReq = req.clone({
      headers: req.headers.set('SessionId', sessionId)
    });
    return next(authReq).pipe(catchError((err) => {
      if (err.status === 423) {
        const modalRef = modalService.open(SessionTimeoutComponent,
          { ariaLabelledBy: 'modal-basic-title', backdrop: 'static' });
        
         modalRef.componentInstance.messageHeader = 'Session Locked';
         modalRef.componentInstance.message = 'Multiple sessions are active, please relogin.';
          
      }
      // Handle unauthorized or forbidden responses by redirecting to an appropriate page
      if (err.status === 401 || err.status === 403) {
        router.navigate(['/unauthorised']);
      }
      return throwError(() => err);
    }));
  }
  return next(req);
};
