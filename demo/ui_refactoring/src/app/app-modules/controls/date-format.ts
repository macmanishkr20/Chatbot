import {
  NgbDateParserFormatter,
  NgbDateStruct,
} from '@ng-bootstrap/ng-bootstrap';
import { Injectable } from '@angular/core';

@Injectable()
export class NgbDateCustomParserFormatter extends NgbDateParserFormatter {
  parse(value: string): NgbDateStruct {
    if (value) {
      const dateParts = value.trim().split('/');
      if (dateParts.length === 1 && isNumber(dateParts[0])) {
        return { day: toInteger(dateParts[0]), month: 0, year: 0 };
      } else if (
        dateParts.length === 2 &&
        isNumber(dateParts[0]) &&
        isNumber(dateParts[1])
      ) {
        return {
          day: toInteger(dateParts[0]),
          month: toInteger(dateParts[1]),
          year: 0,
        };
      } else if (
        dateParts.length === 3 &&
        isNumber(dateParts[0]) &&
        isNumber(dateParts[1]) &&
        isNumber(dateParts[2])
      ) {
        return {
          day: toInteger(dateParts[0]),
          month: toInteger(dateParts[1]),
          year: toInteger(dateParts[2]),
        };
      }
    }
    return { day: 0, month: 0, year: 0 };
  }

  format(date: NgbDateStruct): string {
    return date
      ? `${isNumber(date.day) ? padNumber(date.day) : ''} ${
          isNumber(date.month) ? MonthName(date.month) : ''
        } ${date.year}`
      : '';
  }
}
export function toInteger(value: any): number {
  return parseInt(`${value}`, 10);
}

export function isNumber(value: any): value is number {
  return !isNaN(toInteger(value));
}

export function padNumber(value: number) {
  if (isNumber(value)) {
    return `0${value}`.slice(-2);
  } else {
    return '';
  }
}

export function MonthName(value: number) {
  const months: { [key: number]: string } = {
    1: 'Jan',
    2: 'Feb',
    3: 'Mar',
    4: 'Apr',
    5: 'May',
    6: 'Jun',
    7: 'Jul',
    8: 'Aug',
    9: 'Sep',
    10: 'Oct',
    11: 'Nov',
    12: 'Dec',
  };
  try {
    return months[value];
  } catch {
    return '';
  }
}
