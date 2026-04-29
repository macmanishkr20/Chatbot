import { Component } from '@angular/core';
import { AccessControlComponent } from '../../../../settings/pages/access-control/access-control.component';

@Component({
  selector: 'app-user-management',
  imports: [AccessControlComponent],
  templateUrl: './user-management.component.html',
  styleUrls: ['./user-management.component.scss'],
})
export class UserManagementComponent {

}
