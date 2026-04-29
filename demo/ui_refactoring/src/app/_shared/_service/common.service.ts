import { Injectable } from '@angular/core';
import { ValidationErrors } from '@angular/forms';
import { ToastService } from '../toast-global/toast.service';
import { LoadingService } from '../messaging-service/loading.service';

@Injectable({
  providedIn: 'root',
})
export class CommonService {
  constructor(private toast: ToastService, private loader: LoadingService) {}

  formatCurrency(
    value: number,
    currencyCode: string = 'USD',
    currencyDisplay:
      | 'symbol'
      | 'narrowSymbol'
      | 'code'
      | 'name'
      | undefined = 'symbol',
    showCurrency: boolean = true
  ): string {
    if (!showCurrency) {
      return value.toLocaleString('en-US', {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      });
    }
    return value.toLocaleString('en-US', {
      style: 'currency',
      currency: currencyCode,
      currencyDisplay: currencyDisplay,
    });
  }

  findInvalidControls(
    controls: any,
    controlIdMapping: any,
    tabName?: string,
    showToast: boolean = true
  ): void {
    const invalid: { name: string; errors: ValidationErrors | null }[] = [];
    for (const name in controls) {
      if (controls[name].invalid) {
        const elementId = controlIdMapping[name] || name; // Fallback to 'Unknown Element ID' if not found
        invalid.push({ name, errors: controls[name].errors });
        if (!tabName) {
          const message = `Please correct ${elementId}`;
          if (showToast) this.toast.showError(message); // Show the appropriate message in the toast
        }
      }
    }
    if (tabName && invalid.length > 0) {
      const message = `Please correct the validations in ${tabName}`;
      if (showToast) this.toast.showError(message); // Show the common message in the toast
    }
    console.log('Invalid controls: ', invalid);
    this.loader.hide();
  }

  formatPricingPlan(value: any): string {
    return value != null && value.toString().length <= 5
      ? value.toString().padStart(6, '0')
      : value?.toString() ?? '';
  }

  formatNumber(value: number): string {
    return value.toLocaleString('en-US', {
      minimumFractionDigits: 2, // Ensure two decimal places
      maximumFractionDigits: 2, // Ensure two decimal places
    });
  }

  displayUser(value: any): string {
    return value.split(' (')[0];
  }
}
