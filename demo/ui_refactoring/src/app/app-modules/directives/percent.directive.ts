import {
  Directive,
  ElementRef,
  HostListener,
} from '@angular/core';
import { NgControl } from '@angular/forms';
import { take } from 'rxjs/operators';

@Directive({
  selector: '[appPercent]',
})
export class PercentDirective {
  constructor(private el: ElementRef, private control: NgControl) {}
  @HostListener('blur')
  onInput(): void {
    const value = this.el.nativeElement.value + '';
    if (value && value != '' && !value.endsWith('%')) {
      this.el.nativeElement.value = value + '%';
    }
  }
  @HostListener('focus')
  onFocus(): void {
    const value = this.el.nativeElement.value + '';
    if (value && value != '' && value.endsWith('%')) {
      this.el.nativeElement.value = value.replace('%', '');
    }
  }

  ngOnInit(): void {
    // const value = this.el.nativeElement.value + '';
    // if (value && value != '' && !value.endsWith('%')) {
    //   this.el.nativeElement.value = value + '%';
    // }
    // if (this.control && this.control.control) {
    //   this.control.control.valueChanges.pipe(take(1)).subscribe((value) => {
    //     value = value + '';
    //     if (value && value !== '' && !value.endsWith('%')) {
    //       this.el.nativeElement.value = value + '%';
    //     }
    //   });
    // }
  }
}
