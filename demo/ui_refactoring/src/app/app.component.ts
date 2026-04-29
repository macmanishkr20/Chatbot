import { Component, Inject, OnDestroy, OnInit } from '@angular/core';
import { Router, RouterOutlet } from '@angular/router';
import {
  MSAL_GUARD_CONFIG,
  MsalBroadcastService,
  MsalGuardConfiguration,
  MsalService,
} from '@azure/msal-angular';
import { InteractionStatus, RedirectRequest } from '@azure/msal-browser';
import {
  catchError,
  filter,
  finalize,
  Subject,
  take,
  takeUntil,
  throwError,
} from 'rxjs';
import { AuthService } from './_shared/messaging-service/auth.service';
import { AuthUser } from './_shared/messaging-service/auth-user';
import { ToastService } from './_shared/toast-global/toast.service';
import { LoginService } from './_shared/_service/login.service';
// import { MenuService } from './_shared/messaging-service/menu.service';
import { AfterLoginComponent } from './app-layout/after-login/after-login.component';
import { ToastGlobalComponent } from './_shared/toast-global/toast-global.component';
import {
  NgbModal,
  NgbModalOptions,
  NgbToastModule,
} from '@ng-bootstrap/ng-bootstrap';
import { LoaderComponent } from './_shared/components/loader/loader.component';
import { UserIdleService } from 'angular-user-idle';
import { SessionTimeoutComponent } from './_shared/components/session-timeout/session-timeout.component';
import { BeginLoginService } from './_shared/_service/begin-login.service';

@Component({
  imports: [
    ToastGlobalComponent,
    NgbToastModule,
    LoaderComponent,
    AfterLoginComponent,
  ],
  selector: 'app-root',
  templateUrl: './app.component.html',
  styleUrl: './app.component.scss',
})
export class AppComponent implements OnInit, OnDestroy {
  title = 'MENA CHAT BE';

  isIframe = false;
  loginDisplay = false;
  private loginRequested = false;
  private readonly _destroying$ = new Subject<void>();

  constructor(
    @Inject(MSAL_GUARD_CONFIG) private msalGuardConfig: MsalGuardConfiguration,
    private authService: MsalService,
    private msalBroadcastService: MsalBroadcastService,
    private router: Router,
    private toastService: ToastService,
    private loginService: LoginService,
    private loginMessageService: AuthService<AuthUser>,
    private userIdle: UserIdleService,
    private modalService: NgbModal,
    private loginEvent: BeginLoginService
  ) {}

  ngOnDestroy(): void {
    this._destroying$.next(undefined);
    this._destroying$.complete();
  }

  // ngOnInit(): void {
  //   this.authService.handleRedirectObservable().subscribe();

  //   this.isIframe = window !== window.parent && !window.opener; // Remove this line to use Angular Universal

  //   this.msalBroadcastService.inProgress$
  //     .pipe(
  //       filter(
  //         (status: InteractionStatus) => status === InteractionStatus.None
  //       ),
  //       takeUntil(this._destroying$)
  //     )
  //     .subscribe(() => {
  //       this.setLoginDisplay();
  //       this.checkAndSetActiveAccount();
  //     });
  //   this.intializeTimer();
  // }
  ngOnInit(): void {
    // this.authService.handleRedirectObservable().subscribe();

    // this.msalBroadcastService.inProgress$
    //   .pipe(
    //     filter(
    //       (status: InteractionStatus) => status === InteractionStatus.None
    //     ),
    //     takeUntil(this._destroying$)
    //   )
    //   .subscribe(() => {
    //     this.setLoginDisplay();
    //     // this.checkAndSetActiveAccount();
    //     this.tryLogin();
    //   });
    this.authService.handleRedirectObservable().subscribe({
      next: (result) => {
        if (result !== null && result.account !== null) {
          console.log('result from', result);
          this.authService.instance.setActiveAccount(result.account);
          this.setLoginDisplay();
          this.loginEvent.ssoComplete();
          this.loadAppUser();
        }
      },
      error: (error) => {
        console.error('error from', error);
      },
    });

    this.isIframe = window !== window.parent && !window.opener; // Remove this line to use Angular Universal

    this.loginEvent.startLogin().subscribe(() => {
      this.loginRequested = true;
      this.tryLoginWhenIdle();
    });
    this.intializeTimer();
  }

  private tryLoginWhenIdle() {
    this.msalBroadcastService.inProgress$
      .pipe(
        filter((status: InteractionStatus) => status === InteractionStatus.None),
        take(1)
      )
      .subscribe(() => {
        if (!this.loginRequested) {
          return;
        }

        this.loginRequested = false;
        this.tryLogin();
      });
  }

  setLoginDisplay() {
    this.loginDisplay = this.authService.instance.getAllAccounts().length > 0;
  }

  checkAndSetActiveAccount() {
    /**
     * If no active account set but there are accounts signed in, sets first account to active account
     * To use active account set here, subscribe to inProgress$ first in your component
     * Note: Basic usage demonstrated. Your app may require more complicated account selection logic
     */
    let activeAccount = this.authService.instance.getActiveAccount();

    if (
      !activeAccount &&
      this.authService.instance.getAllAccounts().length > 0
    ) {
      let accounts = this.authService.instance.getAllAccounts();
      this.authService.instance.setActiveAccount(accounts[0]);

      this.loadAppUser();
    } else {
      this.tryLogin();
    }
  }

  tryLogin() {
    if (this.authService.instance.getAllAccounts().length <= 0) {
      this.loginUser();
    }
  }

  loginUser() {
    if (this.msalGuardConfig.authRequest) {
      this.authService.loginRedirect({
        ...this.msalGuardConfig.authRequest,
      } as RedirectRequest);
    } else {
      this.authService.loginRedirect();
    }
  }

  loadAppUser() {
    const t = this.toastService.maual(
      'Please wait, validating the information'
    );
    this.loginMessageService.remove();

    this.loginService
      .validate()
      .pipe(
        finalize(() => {
          this.toastService.remove(t);
        }),
        catchError((err) => {
          sessionStorage.clear();
          this.loginMessageService.remove();

          this.toastService.showError('Failed to validate the user');
          this.router.navigate(['/denied']);
          return throwError(() => new Error(err));
        })
      )
      .subscribe((p) => {
        if (p.succeeded) {
          this.loginMessageService.user = AuthUser.Create(
            p.sessionId,
            p.email,
            p.userId,
            p.firstName,
            p.lastName,
            p.claims,
            p.menus,
            p.userInfoId,
            p.profilePicUrl
          );
        } else {
          this.toastService.showError('Failed to validate the user');
        }
      });
  }

  intializeTimer() {
    this.userIdle.setConfigValues({ idle: 1200, timeout: 1, ping: 120 }); // Set idle to 20 minutes (1200 seconds)
    this.userIdle.startWatching();

    this.userIdle.onTimerStart().subscribe(() => {});

    // Ensure only one popup appears after session timeout.
    let isPopupOpen = false;

    this.userIdle.onTimeout().subscribe(() => {
      if (!isPopupOpen) {
        isPopupOpen = true;
        const ngbModalOptions: NgbModalOptions = {
          backdrop: 'static',
          keyboard: false,
        };

        const modalRef = this.modalService.open(
          SessionTimeoutComponent,
          ngbModalOptions
        );
        modalRef.result.finally(() => {
          isPopupOpen = false;
        });
      }
    });
  }
}
