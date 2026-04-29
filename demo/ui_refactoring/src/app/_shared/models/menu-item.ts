export interface MenuItem {
  direction: string;
  id: string;
  key: string; // this key should map to the key specified in the route navigation
  name: string;
  url: string;
  // parentId: number;
  // isLeaf: boolean;
  // displayOrder: number;
  // chainParent: string;
  menus: MenuItem[];
}

export interface MenuItems {
  menus: MenuItem[];
}

export interface Menu {
  id: number;
  parentId: number;
  code: string;
  name: string;
  icon: string;
  url: string;
  displayOrder: number;
  isLeaf: boolean;
  isFeature: boolean;
}

export interface ParentId {
  id: number;
  name: string;
}
