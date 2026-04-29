import { CommonModule } from '@angular/common';
import { Component, inject, type OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { NgbModal, NgbPaginationModule } from '@ng-bootstrap/ng-bootstrap';
import { Pagination } from '../../../../_shared/models/pagination';
import { UserModel } from './models/user-model';
import { DataService } from './data.service';
import { Role } from './models/role';
import { AddComponent } from './add/add.component';
import { AlertPopupComponent } from '../../../../_shared/components/alert-popup/alert-popup.component';
import { ToastService } from '../../../../_shared/toast-global/toast.service';

@Component({
  selector: 'app-access-control',
  imports: [CommonModule, FormsModule, NgbPaginationModule],
  templateUrl: './access-control.component.html',
  styleUrl: './access-control.component.scss',
})
export class AccessControlComponent
  extends Pagination<UserModel>
  implements OnInit
{
  roles: Role[] = [];

  private _searchTerm: string = '';
  get searchTerm(): string {
    return this._searchTerm;
  }
  set searchTerm(value: string) {
    this._searchTerm = value;
    this._data = this.search(value);
  }

  private toast = inject(ToastService);
  public modalService = inject(NgbModal);
  private dataService = inject(DataService);
  constructor() {
    super();
  }

  ngOnInit(): void {
    this.dataService.roles().subscribe((role) => {
      if (role.success) {
        this.roles =
          role.result?.filter((item) => item.name !== 'Employee') ?? [];
      }
    });

    this.load();
  }

  load() {
    this.dataService.users().subscribe((p) => {
      this._data = [];
      if (p.success) {
        this.setData(p.result ?? []);
      }
    });
  }

  deleteUser(user: UserModel) {
    const confirmRef = this.modalService.open(AlertPopupComponent, { size: 'lg' });
          confirmRef.componentInstance.title = 'Delete User';
          confirmRef.componentInstance.type = 'confirm';
          confirmRef.componentInstance.message = 'Are you sure you want to delete this user ?';
    
          confirmRef.componentInstance.passConfirmation.subscribe((response: boolean) => {
            if (response) {
          this.deleteUserData(user);
      }
    });
  }

  deleteUserData(user: UserModel) {
    this.dataService.deleteUser(user.userId).subscribe(() => {
      this.toast.showSuccess('Successfully deleted the user');
      this.load();
    });
  }

  editClicked(user: UserModel) {
    if (user) {
      this.showModal(user);
    }
  }

  showModal(user: UserModel) {
    const modalRef = this.modalService.open(AddComponent, { size: 'lg' });
    modalRef.componentInstance.roles = this.roles;
    modalRef.componentInstance.user = user;
    modalRef.result.then((result) => {
      if (result === 'success') {
        this.load();
      }
    });
  }

  search(serachString: string): UserModel[] {
    return this._rawData.filter(
      (p) =>
        p.email?.toLowerCase().indexOf(serachString.toLowerCase()) !== -1 ||
        p.role?.toLowerCase().indexOf(serachString.toLowerCase()) !== -1 
    );
  }
  onAddClicked() {
    this.showModal({} as UserModel); 
  }
}
