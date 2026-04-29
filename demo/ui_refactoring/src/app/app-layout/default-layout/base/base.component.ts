import { Component, Input, type OnInit } from '@angular/core';
import { DomSanitizer, SafeUrl } from '@angular/platform-browser';
import { AuthService } from '../../../_shared/messaging-service/auth.service';
import { AuthUser } from '../../../_shared/messaging-service/auth-user';
import { MenuItem, MenuItems } from '../../../_shared/models/menu-item';
import { NgbDropdownModule } from '@ng-bootstrap/ng-bootstrap';

import { RouterModule } from '@angular/router';
import { MenuCenterComponent } from '../menu-center/menu-center.component';
import { MenuLeftComponent } from '../menu-left/menu-left.component';
import { MenuRightComponent } from '../menu-right/menu-right.component';

@Component({
  selector: 'app-layout-base',
  imports: [
    RouterModule,
    NgbDropdownModule,
    MenuCenterComponent,
    MenuLeftComponent,
    MenuRightComponent
],
  templateUrl: './base.component.html',
  styleUrl: './base.component.scss',
})
export class BaseComponent implements OnInit {
  onlyMenu = false;

  @Input()
  title: string = '';

  menus: MenuItem[] = [];

  avatarMenus: MenuItems = { menus: [] };

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
    private sanitizer: DomSanitizer
  ) {}

  ngOnInit(): void {
    Promise.resolve(null).then((e) => {
      this.loginMessageService.statusChanged().subscribe((user) => {
        this.user = user;
        this.menus = user?.menus;
        this._avatarUrl = user?.avatarUrl;

        this.userImage = this.sanitizer.bypassSecurityTrustUrl(user?.avatarUrl);
      });
    });
  }
}
