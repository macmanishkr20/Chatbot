
import { Component, Input, type OnInit } from '@angular/core';
import { DomSanitizer, SafeUrl } from '@angular/platform-browser';
import { Router, RouterModule } from '@angular/router';
import { NgbDropdownModule } from '@ng-bootstrap/ng-bootstrap';
import { AuthUser } from '../../_shared/messaging-service/auth-user';
import { AuthService } from '../../_shared/messaging-service/auth.service';
import { SvgIconComponent } from '../../_shared/components/svg-icon/svg-icon.component';

@Component({
  selector: 'app-no-menu',
  imports: [RouterModule, NgbDropdownModule, SvgIconComponent],
  templateUrl: './no-menu.component.html',
  styleUrl: './no-menu.component.scss',
})
export class NoMenuComponent implements OnInit {
  @Input() title: string = '';

  onlyMenu = false;

  user: AuthUser | null = null;

  userImage: SafeUrl | string = '';

  private _avatarUrl: string = '';
  public get avatarUrl(): string {
    return this._avatarUrl;
  }

  get hasAvatar(): boolean {
    return !(
      this.avatarUrl === null ||
      this.avatarUrl === undefined ||
      this.avatarUrl === ''
    );
  }

  level1Collapsed = true;
  level2Collapsed = true;

  constructor(
    private loginMessageService: AuthService<AuthUser>,
    private sanitizer: DomSanitizer,
    private router: Router
  ) {}

  ngOnInit(): void {
    Promise.resolve(null).then((e) => {
      this.loginMessageService.statusChanged().subscribe((user) => {
        this.user = user;
        // this.menus = user?.menus;
        this._avatarUrl = user?.avatarUrl;

        this.userImage = this.sanitizer.bypassSecurityTrustUrl(user?.avatarUrl);
      });
    });
  }

  logout() {
    this.router.navigate(['/logoff']);
  }
}
