import { Component, type OnInit } from '@angular/core';
import { Router, ActivatedRoute } from '@angular/router';
import { AuthService } from '../../messaging-service/auth.service';
import { AuthUser } from '../../messaging-service/auth-user';
// import { MenuService } from '../../messaging-service/menu.service';

@Component({
  selector: 'app-signin-oidc',
  imports: [],
  templateUrl: './signin-oidc.component.html',
  styleUrl: './signin-oidc.component.scss',
})
export class SigninOidcComponent implements OnInit {
  constructor(
    private router: Router,
    private route: ActivatedRoute,
    private loginMessageService: AuthService<AuthUser>
  ) {}

  ngOnInit(): void {
    const redirectUrl =
      this.route.snapshot.queryParams['returnUrl'] || '/features';

    this.loginMessageService.statusChanged().subscribe((p) => {
      if (p && p.menus?.length > 0) {
        this.router.navigate([redirectUrl]);
      }
    });
  }
}
