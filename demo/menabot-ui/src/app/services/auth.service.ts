import { Injectable, inject, signal, computed } from '@angular/core';
import { Router } from '@angular/router';
import { DEFAULT_RANK, RankInfo, RANKS } from '../models/rank.models';

const AUTH_KEY = 'menabot_user_email';
const RANK_CODE_KEY = 'menabot_user_rank_code';
const RANK_NAME_KEY = 'menabot_user_rank_name';

@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly router = inject(Router);

  readonly userEmail = signal('');
  readonly isLoggedIn = signal(false);

  /**
   * Mandatory rank fields — sent on every chat request.
   * Defaults to DEFAULT_RANK for demo logins; can be overridden via setRank().
   */
  readonly userRankCode = signal<number>(DEFAULT_RANK.rank_code);
  readonly userRankName = signal<string>(DEFAULT_RANK.rank_name);

  /** Full rank entry resolved from current code+name. */
  readonly userRank = computed<RankInfo>(() => {
    const code = this.userRankCode();
    const name = this.userRankName();
    return (
      RANKS.find(r => r.rank_code === code && r.rank_name === name) ??
      RANKS.find(r => r.rank_code === code) ??
      DEFAULT_RANK
    );
  });

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

  login(email: string, rank?: RankInfo): boolean {
    if (!email.endsWith('@gds.ey.com')) return false;
    localStorage.setItem(AUTH_KEY, email);
    this.userEmail.set(email);
    this.isLoggedIn.set(true);
    // Persist rank too (defaults to DEFAULT_RANK when caller passes nothing).
    const r = rank ?? DEFAULT_RANK;
    this.setRank(r);
    return true;
  }

  /** Update the active rank and persist it to localStorage. */
  setRank(rank: RankInfo): void {
    this.userRankCode.set(rank.rank_code);
    this.userRankName.set(rank.rank_name);
    localStorage.setItem(RANK_CODE_KEY, String(rank.rank_code));
    localStorage.setItem(RANK_NAME_KEY, rank.rank_name);
  }

  logout(): void {
    localStorage.removeItem(AUTH_KEY);
    localStorage.removeItem(RANK_CODE_KEY);
    localStorage.removeItem(RANK_NAME_KEY);
    this.userEmail.set('');
    this.isLoggedIn.set(false);
    this.userRankCode.set(DEFAULT_RANK.rank_code);
    this.userRankName.set(DEFAULT_RANK.rank_name);
    this.router.navigate(['/login']);
  }

  private checkAuth(): void {
    const email = localStorage.getItem(AUTH_KEY);
    if (email) {
      this.userEmail.set(email);
      this.isLoggedIn.set(true);
    }
    // Hydrate rank from storage if available; otherwise keep DEFAULT_RANK.
    const storedCode = localStorage.getItem(RANK_CODE_KEY);
    const storedName = localStorage.getItem(RANK_NAME_KEY);
    if (storedCode && storedName) {
      const code = Number(storedCode);
      if (!Number.isNaN(code)) {
        this.userRankCode.set(code);
        this.userRankName.set(storedName);
      }
    }
  }
}
