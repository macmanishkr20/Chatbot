import { Injectable } from '@angular/core';
import { Observable, BehaviorSubject } from 'rxjs';
import { environment } from '../../../environments/environment';

export class Layout {
  name = '';
  get ishorizontal(): boolean {
    return this.name.toLocaleLowerCase() === 'horizontal';
  }
  get isvertical(): boolean {
    return this.name.toLowerCase() === 'vertical';
  }
  get ismobile(): boolean {
    return this.name.toLowerCase() === 'mobile';
  }
}

@Injectable({
  providedIn: 'root',
})
export class LayoutService {
  private subject = new BehaviorSubject<Layout>({} as Layout);

  constructor() {
    const a = new Layout();
    a.name = environment.layout;

    this.subject.next(a);
  }

  layoutChanged(): Observable<Layout> {
    return this.subject.asObservable();
  }
}
