import { Injectable, inject, signal, computed } from '@angular/core';
import { Router } from '@angular/router';

const AUTH_KEY = 'menabot_user_email';

@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly router = inject(Router);

  readonly userEmail = signal('');
  readonly isLoggedIn = signal(false);

  readonly displayName = computed(() => {
    const email = this.userEmail();
    if (!email) return '';
    const name = email.split('@')[0];
    return name
      .split('.')
      .map(part => part.charAt(0).toUpperCase() + part.slice(1))
      .join(' ');
  });

  readonly userInitial = computed(() => {
    const name = this.displayName();
    return name ? name.charAt(0).toUpperCase() : '?';
  });

  constructor() {
    this.checkAuth();
  }

  login(email: string): boolean {
    // Accept any EY regional subdomain: name@{region}.ey.com
    if (!/^[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+\.ey\.com$/.test(email)) return false;
    localStorage.setItem(AUTH_KEY, email);
    this.userEmail.set(email);
    this.isLoggedIn.set(true);
    return true;
  }

  logout(): void {
    localStorage.removeItem(AUTH_KEY);
    this.userEmail.set('');
    this.isLoggedIn.set(false);
    this.router.navigate(['/login']);
  }

  private checkAuth(): void {
    const email = localStorage.getItem(AUTH_KEY);
    if (email) {
      this.userEmail.set(email);
      this.isLoggedIn.set(true);
    }
  }
}
