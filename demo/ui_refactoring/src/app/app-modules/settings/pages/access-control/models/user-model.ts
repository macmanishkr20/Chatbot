export class UserModel {
  username: string = '';
  email: string = '';
  role: string = '';
  country: string = '';
  userId: string = '';
  firstName: string = '';
  lastName: string = '';
  countryIds: number[] = [];
  id: string = ''; // this and userId are the same
  userInfoId: number = 0;
}
