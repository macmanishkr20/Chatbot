import { Menu, MenuItem } from '../models/menu-item';

export class AuthUser {
  private constructor() {}

  private _userid: string = '';
  private _meid: number = 0;
  private _sessionId: string = '';
  private _firstName: string = '';
  private _lastName: string = '';
  private _username: string = '';
  private _roles: any = null;
  private _modules: any = null;
  private _features: any = null;
  private _claims: Claim[] = [];
  private _email: string = '';
  private _avatarUrl: string | undefined = '';
  private _menus: MenuItem[] = [];
  private _userInfoId: number = 0;
  private _isSuperAdmin: boolean = false;

  static Clone(value: AuthUser): AuthUser {
    const user = new AuthUser();
    user._sessionId = value._sessionId;
    user._meid = value._meid;
    user._firstName = value._firstName;
    user._lastName = value._lastName;
    user._avatarUrl = value._avatarUrl;
    user._claims = value._claims;
    user._email = value._email;
    user._menus = value._menus;
    user._userInfoId = value._userInfoId;
    user._isSuperAdmin = value._isSuperAdmin;
    user.setToken();

    return user;
  }

  static Create(
    sessionId: string,
    email: string,
    meId: number,
    firstName: string,
    lastName: string,
    claims: Claim[],
    menus: MenuItem[],
    userInfoId: number,
    avatarUrl?: string
  ): AuthUser {
    const user = new AuthUser();
    user._sessionId = sessionId;
    user._meid = meId;
    user._firstName = firstName;
    user._lastName = lastName;
    user._avatarUrl = avatarUrl;
    user._claims = claims;
    user._email = email;
    user._menus = menus;
    user._userInfoId = userInfoId;
    user._isSuperAdmin = claims.some(c => c.key === 'AppRole' 
      && c.value.toUpperCase() === 'SUPER_ADMIN');
    user.setToken();

    return user;
  }

   get avatarUrl(): string {
    return this._avatarUrl ?? '';
  }

  get isAuthenticated(): boolean {
    if (this._claims) {
      return true;
    }
    return false;
  }

  get id(): string {
    return this._userid;
  }

  get sessionId(): string {
    return this._sessionId;
  }

  get email(): string {
    return this._email;
  }

  get meId(): number {
    return this._meid;
  }

  get firstName(): string {
    return this._firstName;
  }

  get lastName(): string {
    return this._lastName;
  }

  get fullName(): string {
    return `${this._firstName} ${this._lastName}`;
  }

  get username(): string {
    return this._username;
  }

  get userInfoId(): number {
    return this._userInfoId;
  }

  get menus(): MenuItem[] {
    return this._menus;
  }

  get roles(): Claim[] {
    return this.parseClaims('roles', this._roles);
  }

  get modules(): Claim[] {
    return this.parseClaims('modules', this._modules);
  }

  get features(): Claim[] {
    return this.parseClaims('features', this._features);
  }

    get isSuperAdmin(): boolean {
    return this._claims.some(c => c.key === 'AppRole' 
                        && c.value.toUpperCase() === 'SUPER_ADMIN');
  }

  private parseClaims(key: string, c: any) {
    const claims: Claim[] = [];

    if (c instanceof Array) {
      c.forEach((value) => {
        claims.push(value);
      });
    } else if (typeof c === 'string') {
      claims.push({ key: key.toLowerCase(), value: c });
    }

    return claims;
  }

  updateToken(token: string, refreshToken: string) {
    // this._token = token;
    // this._refreshToken = refreshToken;
  }

  private setToken() {
    if (this._claims) {
      this._features = this._claims.filter((v) => v.key === 'FEATURE');
      this._modules = this._claims.filter((v) => v.key === 'MODULE');
      const roleClaim = this._claims.find(
        (v) =>
          v.key ===
          'http://schemas.microsoft.com/ws/2008/06/identity/claims/role'
      );
      this._roles = roleClaim ? roleClaim.value : '';
      const usernameClaim = this._claims.find(
        (v) =>
          v.key === 'http://schemas.xmlsoap.org/ws/2005/05/identity/claims/name'
      );
      this._username = usernameClaim ? usernameClaim.value : '';
      const userIdClaim = this._claims.find(
        (v) =>
          v.key ===
          'http://schemas.xmlsoap.org/ws/2005/05/identity/claims/nameidentifier'
      );
      this._userid = userIdClaim ? userIdClaim.value : '';
    }
  }

  toJSON() {
    const proto = Object.getPrototypeOf(this);
    const jsonObj: any = Object.assign({}, this);

    Object.entries(Object.getOwnPropertyDescriptors(proto))
      .filter(([key, descriptor]) => typeof descriptor.get === 'function')
      .map(([key, descriptor]) => {
        if (descriptor && key[0] !== '_') {
          try {
            const val = (this as any)[key];
            jsonObj[key] = val;
          } catch (error) {
            console.error(`Error calling getter ${key}`, error);
          }
        }
      });

    return jsonObj;
  }

}

export interface Claim {
  key: string;
  value: string;
}

export interface UserData {
  features: Claim[];
  modules: Claim[];
}
