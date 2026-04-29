import { Component, type OnInit } from '@angular/core';
import { Router } from '@angular/router';
import { NgbActiveModal } from '@ng-bootstrap/ng-bootstrap';

@Component({
  selector: 'app-session-timeout',
  imports: [],
  templateUrl: './session-timeout.component.html',
  styleUrls: ['./session-timeout.component.scss'],
})
export class SessionTimeoutComponent implements OnInit {
  constructor(public activeModal: NgbActiveModal, private router: Router) {}

  ngOnInit(): void {}
  relogin() {
    this.router.navigate(['/logoff']);
  }
}
