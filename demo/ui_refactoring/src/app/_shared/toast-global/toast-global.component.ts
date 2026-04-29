import { Component, TemplateRef, type OnInit } from '@angular/core';
import { NgbToastModule } from '@ng-bootstrap/ng-bootstrap';
import { ToastService } from './toast.service';
import { CommonModule } from '@angular/common';

@Component({
  selector: 'app-toast-global',
  imports: [CommonModule, NgbToastModule],
  templateUrl: './toast-global.component.html',
  styleUrl: './toast-global.component.scss',
  host: {
    class: 'toast-container position-fixed top-0 end-0 p-2',
    style: 'z-index: 1200',
  },
})
export class ToastGlobalComponent implements OnInit {
  constructor(public toastService: ToastService) {}

  ngOnInit(): void {}

  isTemplate(toast: any) {
    return toast.textOrTpl instanceof TemplateRef;
  }
}
