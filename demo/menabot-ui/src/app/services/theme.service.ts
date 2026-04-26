import { Injectable, signal } from '@angular/core';

const THEME_KEY = 'menabot_theme';

@Injectable({ providedIn: 'root' })
export class ThemeService {
  readonly isDark = signal(true);

  constructor() {
    const stored = localStorage.getItem(THEME_KEY);
    const dark = stored ? stored === 'dark' : true;
    this.isDark.set(dark);
    document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light');
  }

  toggle(): void {
    const dark = !this.isDark();
    this.isDark.set(dark);
    localStorage.setItem(THEME_KEY, dark ? 'dark' : 'light');
    document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light');
  }
}
