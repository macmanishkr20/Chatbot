import { Component, type OnInit, Input } from '@angular/core';
import { BeginLoginService } from '../../_shared/_service/begin-login.service';
import { AuthService } from '../../_shared/messaging-service/auth.service';
import { AuthUser } from '../../_shared/messaging-service/auth-user';
import { MsalService } from '@azure/msal-angular';
import { RouterOutlet } from '@angular/router';

@Component({
  selector: 'app-before-login',
  imports: [RouterOutlet],
  templateUrl: './before-login.component.html',
  styleUrl: './before-login.component.scss',
})
export class BeforeLoginComponent implements OnInit {
  loggedIn = false;
  disabled = false;
  taFilePath: string = '';

  @Input()
  title: string = '';
  constructor(
    private loginService: BeginLoginService,
    private authService: AuthService<AuthUser>,
    private msalService: MsalService
  ) {}

  ngOnInit(): void {
    this.authService.remove();
    if (this.msalService.instance.getAllAccounts().length > 0) {
      this.msalService.logoutRedirect();
      return;
    }

    this.loginService.ssoCompleted().subscribe((p) => {
      console.log('SSO completed');

      this.loggedIn = p;
    });
    //if auto authenitcation required, enable below code
    this.onLaunch();
  }

  onLaunch() {
    this.loginService.start();
    this.disabled = true;
  }

}
