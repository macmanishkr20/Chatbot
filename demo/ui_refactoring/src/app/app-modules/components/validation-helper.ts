import {
  AbstractControl,
  FormGroup,
  ValidationErrors,
  ValidatorFn,
} from '@angular/forms';

export function numberValidator(): ValidatorFn {
  return (control: AbstractControl): ValidationErrors | null => {
    const data = control.value;
    var value = data ?? null;
    if (value && isNaN(value)) {
      return { notANumber: true };
    }
    return null;
  };
}
export function wholeNumberValidator(): ValidatorFn {
  return (control: AbstractControl): ValidationErrors | null => {
    const data = control.value;
    var value = data ?? null;
    if (value && isNaN(value)) {
      return { notANumber: true };
    }
    if (value && value.toString().includes('.')) {
      return { hasDecimal: true };
    }
    return null;
  };
}
export function nameValidator(): ValidatorFn {
  const regex = /^[a-zA-Z0-9@&()/ :"\-_\[\];'.*,\\]*$/;
  return (control: AbstractControl): ValidationErrors | null => {
    const value = control.value;
    if (value === null || value === '') {
      return null;
    }
    return regex.test(value) ? null : { nameValidator: true };
  };
}
export function userNameValidator(): ValidatorFn {
  const regex = /^[a-zA-Z0-9@#&()/ :"\-_\[\];'.*,\\]*$/;
  return (control: AbstractControl): ValidationErrors | null => {
    const value = control.value;
    if (value === null || value === '') {
      return null;
    }
    return regex.test(value) ? null : { nameValidator: true };
  };
}
export function postiveNumberValidator(): ValidatorFn {
  return (control: AbstractControl): ValidationErrors | null => {
    const data = control.value;
    var value = data ?? null;
    if (value && isNaN(value)) {
      return { notANumber: true };
    }
    if (value && value < 0) {
      return { negativeNumber: true };
    }
    return null;
  };
}

export function endDateAfterStartDateValidator(
  startDateKey: string,
  endDateKey: string
): ValidatorFn {
  return (control: AbstractControl): ValidationErrors | null => {
    const formGroup = control as FormGroup;
    const startDate = formGroup.get(startDateKey)?.value;
    const endDate = formGroup.get(endDateKey)?.value;
    var key = startDateKey + '_' + endDateKey;
    if (startDate && endDate) {
      var sDate = new Date(startDate.year, startDate.month - 1, startDate.day);
      var eDate = new Date(endDate.year, endDate.month - 1, endDate.day);
      if (startDate && endDate && sDate >= eDate) {
        return { [key]: true };
      }
    }
    return null;
  };
}

export function decimalValidator(): ValidatorFn {
  return (control: AbstractControl): ValidationErrors | null => {
    const validDecimalRegex = /^-?\d*(\.\d{0,2})?$/;
    const value = control.value;
    if (value === null || value === '') {
      return null; // don't validate empty value to allow optional controls
    }
    return validDecimalRegex.test(value) ? null : { invalidDecimal: true };
  };
}
