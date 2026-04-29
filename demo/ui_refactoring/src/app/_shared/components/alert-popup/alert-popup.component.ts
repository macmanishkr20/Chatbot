import { CommonModule } from '@angular/common';
import {
  Component,
  EventEmitter,
  inject,
  Input,
  Output,
  TemplateRef,
  ViewEncapsulation,
  type OnInit,
} from '@angular/core';
import { NgbModal } from '@ng-bootstrap/ng-bootstrap';
import { NgbActiveModal } from '@ng-bootstrap/ng-bootstrap';

@Component({
  selector: 'app-alert-popup',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './alert-popup.component.html',
  styleUrl: './alert-popup.component.scss',
  encapsulation: ViewEncapsulation.None,
})
export class AlertPopupComponent implements OnInit {
  private modalService = inject(NgbModal);
  @Input() message: string = '';
  @Input() title: string = '';
  @Input() showClose: boolean = true;
  @Input() type: string = 'alert';
  @Input() yesButtonText: string = 'Yes';
  @Input() noButtonText: string = 'No';
  @Output() passConfirmation: EventEmitter<any> = new EventEmitter();

  constructor(public activeModal: NgbActiveModal) {}
  ngOnInit(): void {}

  passConfirmationBack(isConfirmed: boolean) {
    this.passConfirmation.emit(isConfirmed);
    this.activeModal.close();
  }
}
