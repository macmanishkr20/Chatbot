import { Injectable } from '@angular/core';
import { BehaviorSubject } from 'rxjs/internal/BehaviorSubject';
import { NavigationEnd, Router } from '@angular/router';
import { Observable } from 'rxjs';
import { filter } from 'rxjs/operators';

@Injectable({
  providedIn: 'root'
})
export class RouteService {
  private subject = new BehaviorSubject<NavigationEnd>({} as NavigationEnd);

  constructor(private route: Router) {
    this.route.events
      .pipe(filter(e => e instanceof NavigationEnd))
      .subscribe(p => {
        this.subject.next((<NavigationEnd>p));
      });
  }

  routeChanged(): Observable<NavigationEnd> {
    return this.subject.asObservable();
  }
}
