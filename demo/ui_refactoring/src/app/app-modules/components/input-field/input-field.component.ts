import { CommonModule } from '@angular/common';
import { Component, Input, type OnInit } from '@angular/core';
import {
  AbstractControl,
  FormControl,
  FormsModule,
  ReactiveFormsModule,
} from '@angular/forms';
import { NgbPopoverModule } from '@ng-bootstrap/ng-bootstrap';

@Component({
  selector: 'app-input-field',
  imports: [CommonModule, FormsModule, ReactiveFormsModule, NgbPopoverModule],
  templateUrl: './input-field.component.html',
  styleUrls: ['./input-field.component.scss', '/src/styles.scss'],
})
export class InputFieldComponent implements OnInit {
  @Input() label: string = '';
  @Input() control: AbstractControl | null = new FormControl('');
  @Input() className: string = '';
  @Input() type: string = 'text';
  @Input() placeholder: string = '';
  @Input() validationMessages: { [key: string]: string } = {};
  @Input() maxlength: number = 100;
  @Input() isrequired: boolean = false;
  @Input() infoRequired: boolean = false;
  @Input() infoMessage: string = '';

  get formControl(): FormControl {
    return this.control as FormControl;
  }
  ngOnInit(): void {}
}
