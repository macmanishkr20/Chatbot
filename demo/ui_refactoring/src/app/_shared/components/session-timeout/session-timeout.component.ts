import { Component, Input, type OnInit } from '@angular/core';
import { Router } from '@angular/router';
import { NgbActiveModal } from '@ng-bootstrap/ng-bootstrap';

@Component({
  selector: 'app-session-timeout',
  imports: [],
  templateUrl: './session-timeout.component.html',
  styleUrls: ['./session-timeout.component.scss'],
})
export class SessionTimeoutComponent implements OnInit {
  @Input() message: string = 'Your session has expired. Please log in again.';
  @Input() messageHeader: string = 'Session Expired';
  constructor(public activeModal: NgbActiveModal, private router: Router) {}

  ngOnInit(): void {}
  relogin() {
    this.router.navigate(['/logoff']);
  }
}
