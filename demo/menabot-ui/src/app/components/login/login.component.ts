import { Component, inject, signal, ChangeDetectionStrategy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { AuthService } from '../../services/auth.service';

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
  error = signal('');

  onSubmit(): void {
    const email = this.email().trim();
    if (!email) {
      this.error.set('Please enter your email address.');
      return;
    }
    // Accept any EY regional subdomain: name@{region}.ey.com (e.g. gds, ae, bh, sa…)
    const EY_EMAIL_RE = /^[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+\.ey\.com$/;
    if (!EY_EMAIL_RE.test(email)) {
      this.error.set('Please use your EY email address (e.g. name@gds.ey.com, name@ae.ey.com).');
      return;
    }
    if (this.auth.login(email)) {
      this.router.navigate(['/chat']);
    }
  }
}
