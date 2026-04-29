import { Injectable, TemplateRef } from '@angular/core';

@Injectable({
  providedIn: 'root',
})
export class ToastService {
  public toasts: any[] = [];

  constructor() {}

  show(textOrTpl: string | TemplateRef<any>, options: any = {}) {
    this.toasts.push({ textOrTpl, ...options });
  }

  showSuccess(textOrTpl: string | TemplateRef<any>) {
    const options = {
      classname: 'bg-success text-light',
      autohide: true,
      delay: 5000,
    };

    this.toasts.push({ textOrTpl, ...options });
  }

  showError(textOrTpl: string | TemplateRef<any>) {
    const options = {
      classname: 'bg-danger text-light',
      autohide: true,
      delay: 5000,
    };

    this.toasts.push({ textOrTpl, ...options });
  }

  showWarning(textOrTpl: string | TemplateRef<any>) {
    const options = {
      classname: 'bg-warning text-light',
      autohide: true,
      delay: 5000,
    };

    this.toasts.push({ textOrTpl, ...options });
  }

  maual(textOrTpl: string | TemplateRef<any>) {
    const options = { classname: 'bg-warning text-light', autohide: false };
    const t = { textOrTpl, ...options };
    this.toasts.push(t);
    return t;
  }

  remove(toast: any) {
    this.toasts = this.toasts.filter((t) => t !== toast);
  }
}
