export class MasterModel {
  id: number;
  code: string;
  name: string;
  isActive: boolean;

  constructor(id: number, code: string, name: string, isActive: boolean) {
    this.id = id;
    this.code = code;
    this.name = name;
    this.isActive = isActive;
  }
}
