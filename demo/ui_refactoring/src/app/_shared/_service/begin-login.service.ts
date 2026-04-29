import { Injectable } from '@angular/core';
import { BehaviorSubject, Observable, ReplaySubject } from 'rxjs';

@Injectable({
  providedIn: 'root',
})
export class BeginLoginService {
  private subject = new ReplaySubject<void>(1);
  private ssoSubject = new BehaviorSubject<boolean>(false);

  constructor() {}

  startLogin(): Observable<void> {
    return this.subject.asObservable();
  }

  start() {
    this.subject.next();
  }

  ssoCompleted(): Observable<boolean> {
    return this.ssoSubject.asObservable();
  }

  ssoComplete() {
    this.ssoSubject.next(true);
  }
}
