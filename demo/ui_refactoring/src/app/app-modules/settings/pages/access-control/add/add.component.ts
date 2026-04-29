import { CommonModule } from '@angular/common';
import { Component, inject, Input, type OnInit } from '@angular/core';
import {
  FormBuilder,
  FormGroup,
  FormsModule,
  ReactiveFormsModule,
  Validators,
} from '@angular/forms';
import { NgbActiveModal, NgbModal, NgbTooltipModule, NgbTypeaheadModule } from '@ng-bootstrap/ng-bootstrap';
import { NgSelectModule } from '@ng-select/ng-select';
import { DataService } from '../data.service';
import { ToastService } from '../../../../../_shared/toast-global/toast.service';
import { UserModel } from '../models/user-model';
import { Role } from '../models/role';
import { catchError, debounceTime, distinctUntilChanged, finalize, Observable, of, switchMap, tap } from 'rxjs';
import { AlertPopupComponent } from '../../../../../_shared/components/alert-popup/alert-popup.component';

@Component({
  selector: 'app-add',
  imports: [CommonModule, FormsModule, ReactiveFormsModule, NgbTypeaheadModule, NgbTooltipModule, NgSelectModule],
  templateUrl: './add.component.html',
  styleUrl: './add.component.scss',
})

export class AddComponent implements OnInit {
  @Input() user: UserModel | undefined;
  @Input() roles: Role[] = [];

  action = 'Add';
  selectedUser: any;
  searching = false;
  searchFailed = false;
  isDisabled = false;
  showLoader = false;


  userForm: FormGroup;

  get isedit(): boolean {
    return (
      (this.user &&
        (this.user?.userId != null || this.user?.userId !== undefined)) ??
      false
    );
  }

  get form() {
    return this.userForm.controls;
  }
  private modalService = inject(NgbModal);
  private dataService = inject(DataService);
  public activeModal = inject(NgbActiveModal);
  private toast = inject(ToastService);
  private formBuilder = inject(FormBuilder);

  constructor() {
    this.userForm = this.formBuilder.group({
      userName: [null],
      role: [null, Validators.required],
      email: [null],
      user: [null, Validators.required],
      firstName: [null, Validators.required],
      lastName: [null, Validators.required],
    });
  }

  ngOnInit(): void {
    if (this.isedit) {
      this.editUser(this.user);
      this.action = 'Edit';
    }
  }

  onSubmit() {
    const userControl = this.userForm.controls['user'];
    const userPrincipalName = userControl.value?.userPrincipalName ?? '';
    const userMail = userControl.value?.mail ?? '';

    this.userForm.patchValue({
      userName: userPrincipalName,
      email: userMail
    });

    if (!this.isedit) {
      this.showLoader = true;
      this.dataService.addUser(this.userForm.value)
        .pipe(finalize(() => this.showLoader = false))
        .subscribe({
          next: ({ success, errors }) => {
            if (success) {
              this.toast.showSuccess('Successfully added the user');
              this.activeModal.close('success');
            } else if (errors?.length) {
              this.toast.showError(errors[0]);
            }
          }
        });
      return;
    }

    const userData = {
      userInfoId: this.user?.userInfoId,
      firstName: this.form['firstName'].value,
      lastName: this.form['lastName'].value,
      userName: userPrincipalName,
      email: userMail,
      role: this.form['role'].value?.name,
      userId: this.user?.userId
    };

    const confirmRef = this.modalService.open(AlertPopupComponent, { size: 'lg' });
    confirmRef.componentInstance.title = 'Edit User';
    confirmRef.componentInstance.type = 'confirm';
    confirmRef.componentInstance.message = 'Are you sure you want to update this user ?';

    confirmRef.componentInstance.passConfirmation.subscribe((response: boolean) => {
      if (!response) {
        return;
      }
      this.showLoader = true;
      this.dataService.editUser(userData)
        .pipe(finalize(() => this.showLoader = false))
        .subscribe({
          next: () => {
            this.toast.showSuccess('Successfully updated user information');
            this.activeModal.close('success');
          },
          error: () => {
            this.toast.showError('Failed to edit user information');
          }
        });
    });
  }

  editUser(user: UserModel | undefined) {
    if (user) {
      const r = this.roles.find(item => item.name === user.role);
      this.userForm.controls['userName'].disable();
      this.userForm.controls['email'].disable();
      this.userForm.controls['role'].disable();

      const u = {
        userPrincipalName: user.username,
        mail: user.email
      }

      this.userForm.patchValue({
        userName: user.username,
        role: r,
        email: user.email,
        firstName: user.firstName,
        lastName: user.lastName,
        user: u
      });
    }
  }

  compareModel(c1: Role, c2: Role): boolean {
    return c1 && c2 ? c1.name === c2.name : c1 === c2;
  }
  searchEmail = (text$: Observable<any>) =>
    text$.pipe(
      debounceTime(300),
      distinctUntilChanged(),
      tap(() => this.searching = true),
      switchMap(term =>
        this.dataService.searchUser(term)
          .pipe(tap(() => this.searchFailed = false),
            catchError(() => {
              this.searchFailed = true;
              return of([]);
            }))
      ),
      tap(() => this.searching = false)
    );

  inputFormatterName = (x: { mail?: string } | string | null | undefined): string => {
    if (typeof x === 'string') {
      return x;
    }

    return x?.mail ?? '';
  };
}
