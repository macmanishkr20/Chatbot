import { Component, inject, signal, ChangeDetectionStrategy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { AuthService } from '../../services/auth.service';
import { DEFAULT_RANK, RankInfo, RANKS } from '../../models/rank.models';

@Component({
  selector: 'app-login',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './login.component.html',
  styleUrl: './login.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class LoginComponent {
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);

  email = signal('');
  gui = signal('1016409');  // demo default — overrides via login form
  error = signal('');

  /** Rank selector — defaults to Manager (DEFAULT_RANK). */
  readonly ranks = RANKS;
  rankKey = signal<string>(this.makeKey(DEFAULT_RANK));

  /** Build a stable composite key (rank_code|rank_name) for the <select>. */
  makeKey(r: RankInfo): string {
    return `${r.rank_code}|${r.rank_name}`;
  }

  onSubmit(): void {
    const email = this.email().trim();
    if (!email) {
      this.error.set('Please enter your email address.');
      return;
    }
    if (!email.endsWith('@gds.ey.com')) {
      this.error.set('Please use your @gds.ey.com email address.');
      return;
    }
    const gui = this.gui().trim();
    if (!gui) {
      this.error.set('Please enter your GUI (Employee ID).');
      return;
    }
    const selected = this.ranks.find(r => this.makeKey(r) === this.rankKey()) ?? DEFAULT_RANK;
    if (this.auth.login(email, selected, gui)) {
      this.router.navigate(['/chat']);
    }
  }
}
