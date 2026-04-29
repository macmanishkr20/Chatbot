import { Component, Input, type OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { AuthUser } from '../../_shared/messaging-service/auth-user';
import { AuthService } from '../../_shared/messaging-service/auth.service';
import { Router, RouterOutlet } from '@angular/router';
import { NoMenuComponent } from '../no-menu/no-menu.component';
import { LandingComponent } from '../../app-modules/landing/landing.component';
import { BeforeLoginComponent } from '../before-login/before-login.component';
import { LoginService } from '../../_shared/_service/login.service';
import { NgbModal, NgbModalOptions } from '@ng-bootstrap/ng-bootstrap';
import { PrivacyConsentComponent } from '../../_shared/components/PrivacyConsent/PrivacyConsent.component';

@Component({
  selector: 'app-after-login',
  imports: [CommonModule, RouterOutlet, NoMenuComponent, BeforeLoginComponent],
  templateUrl: './after-login.component.html',
  styleUrl: './after-login.component.scss',
})
export class AfterLoginComponent implements OnInit {
  isIframe = false;
  user: AuthUser | null = null;
  showPA = false;

  @Input()
  title: string = '';

  constructor(
    private loginMessageService: AuthService<AuthUser>,
    private loginService: LoginService,
    private modalService: NgbModal,
    private router: Router
  ) {}

  ngOnInit(): void {
    this.loginMessageService.statusChanged().subscribe((user) => {
      this.user = user;
      if (this.loginMessageService.user.isAuthenticated) {
        this.privacyChecking();
      }
    });
  }

  privacyChecking() {
    this.loginService
      .showPrivacyConsent(this.loginMessageService.user.userInfoId)
      .subscribe((p) => {
        this.showPA = p;
        if (this.showPA) {
          const ngbModalOptions: NgbModalOptions = {
            backdrop: 'static',
            keyboard: false,
            size: 'xl',
          };
          const confirmRef = this.modalService.open(
            PrivacyConsentComponent,
            ngbModalOptions
          );
          confirmRef.componentInstance.passConfirmation.subscribe(
            (response: any) => {
              if (response === true) {
                this.loginService
                  .createPrivacyConsent(
                    this.loginMessageService.user.userInfoId
                  )
                  .pipe()
                  .subscribe();
              } else {
                this.router.navigate(['/logoff']);
              }
            }
          );
        }
      });
  }
}
