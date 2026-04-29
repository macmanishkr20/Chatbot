
import { Component, EventEmitter, Output, type OnInit } from '@angular/core';
import { NgbActiveModal } from '@ng-bootstrap/ng-bootstrap';

@Component({
  selector: 'app-privacy-consent',
  imports: [],
  templateUrl: './PrivacyConsent.component.html',
  styleUrls: ['./PrivacyConsent.component.scss'],
})
export class PrivacyConsentComponent implements OnInit {
  @Output() passConfirmation: EventEmitter<any> = new EventEmitter();
  confirmText: string = 'Agree';
  cancelText: string = 'Logout';
  isUserClicked: boolean = false;
  isConfirmHide: boolean = false;
  toolName = 'MENA Chat BE';
  ngOnInit(): void {}

  constructor(public activeModal: NgbActiveModal) {}

  passConfirmationBack(isConfirmed: boolean) {
    //const confirmModel = new ConfirmModel();
    //confirmModel.isConfirmed = isConfirmed;
    this.passConfirmation.emit(isConfirmed);
    this.activeModal.close();
  }

  agreePIA($event: any): void {
    this.isUserClicked = true;
    if ($event.target.checked == true) {
      this.isConfirmHide = false;
    } else {
      this.isConfirmHide = true;
    }
  }
  notAgreePIA($event: any): void {
    this.isUserClicked = true;
    this.isConfirmHide = true;
  }
}
