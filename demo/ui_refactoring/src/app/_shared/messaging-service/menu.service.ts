// import { Injectable } from '@angular/core';
// import { BehaviorSubject, Observable } from 'rxjs';
// import { HttpClient } from '@angular/common/http';
// import { map } from 'rxjs/operators';
// import { environment } from '../../../environments/environment';
// import { MenuItem, MenuItems } from '../models/menu-item';

// @Injectable({
//   providedIn: 'root',
// })
// export class MenuService {
//   private readonly menuUrl = `${environment.apiUrl}menu`;

//   private menu: MenuItems = { menus: [] };
//   private hide = true;

//   private subject = new BehaviorSubject<MenuItems>(this.menu);
//   private hideSubject = new BehaviorSubject<boolean>(this.hide);

//   constructor(private http: HttpClient) {}

//   loaded(): Observable<MenuItems> {
//     return this.subject.asObservable();
//   }

//   visibilityChanged(): Observable<boolean> {
//     return this.hideSubject.asObservable();
//   }

//   load(menus: MenuItem[]) {
//     const a: MenuItems = { menus: menus };
//     this.subject.next(a);
//     // return this.http.get<any>(`${this.menuUrl}/${roleId}`).pipe(
//     //   map((p) => {
//     //     this.subject.next(p);
//     //     return p;
//     //   })
//     // );
//   }

//   changeVisibility(value: boolean) {
//     return this.hideSubject.next(value);
//   }
// }
