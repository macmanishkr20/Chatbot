import { Component, inject } from '@angular/core';
import { Router } from '@angular/router';

@Component({
  selector: 'app-home',
  imports: [],
  templateUrl: './home.component.html',
  styleUrl: './home.component.scss',
})
export class HomeComponent {

  private readonly router = inject(Router);

  onLaunch() {
    this.router.navigate(['/features/page/chats']);
  }

}
