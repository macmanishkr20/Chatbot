import { Directive, HostListener } from '@angular/core';

@Directive({
  selector: '[appBlockTyping]',
})
export class BlockTypingDirective {
  constructor() {}
  @HostListener('paste', ['$event']) blockPaste(e: KeyboardEvent) {
    e.preventDefault();
  }

  @HostListener('copy', ['$event']) blockCopy(e: KeyboardEvent) {
    e.preventDefault();
  }

  @HostListener('cut', ['$event']) blockCut(e: KeyboardEvent) {
    e.preventDefault();
  }
  @HostListener('keydown', ['$event']) onKeyDown(event: KeyboardEvent) {
    let e = <KeyboardEvent>event;
    if (event.keyCode != 8 && event.keyCode != 46) {
      e.preventDefault();
    }
  }
}
