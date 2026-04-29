import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable, ReplaySubject, map, of, shareReplay } from 'rxjs';

export interface SvgIcon {
  iconName: string;
  iconData: string;
}

@Injectable({
  providedIn: 'root',
})
export class IconService {
  private readonly iconsUrl = 'assets/json/icons.json';
  private icons$?: Observable<Map<string, string>>;

  constructor(private http: HttpClient) {}

  /**
   * Loads the icons.json file once and caches the parsed map of
   * icon name -> raw SVG markup for subsequent lookups.
   */
  private loadIcons(): Observable<Map<string, string>> {
    if (!this.icons$) {
      this.icons$ = this.http.get<SvgIcon[]>(this.iconsUrl).pipe(
        map((icons) => {
          const map = new Map<string, string>();
          (icons ?? []).forEach((i) => map.set(i.iconName, i.iconData));
          return map;
        }),
        shareReplay({ bufferSize: 1, refCount: false })
      );
    }
    return this.icons$;
  }

  /**
   * Returns the raw SVG markup for the given icon name, or an empty
   * string if the icon is not found.
   */
  getIcon(name: string): Observable<string> {
    if (!name) {
      return of('');
    }
    return this.loadIcons().pipe(map((icons) => icons.get(name) ?? ''));
  }
}
