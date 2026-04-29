export class UserVM {
  username?: string;
  password?: string;
  email?: string;
  id!: string;
  excludeRolesFromSearch?: [];
  role?: string;
  roleId?: string;
  roleCode?: string;
  firstName?: string;
  lastName?: string;
}

export interface Claim {
  key: string;
  value: string;
}

export class UserInfoVM {
  userId: string = '';
  firstName?: string;
  lastName?: string;
  userInfoId: number = 0;
  email: string = '';
  claims?: Claim[];
  isActive: boolean = true;
  username?: string;
  sessionId?: string;
  role?: string;
  userMenus?: MenuVM[];
}

export class MenuVM {
  id!: number;
  key!: string;
  name?: string;
  url?: string;
  parentId?: number;
  isLeaf: boolean = false;
  displayOrder: number = 0;
  chainParent?: string;
  icon?: string;
  iconOnly: boolean = false;
  menus: MenuVM[] = [];
  direction: string = '';
}
