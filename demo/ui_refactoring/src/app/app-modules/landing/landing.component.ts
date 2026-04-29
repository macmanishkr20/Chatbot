import { Component, Input, type OnInit } from '@angular/core';
import { AfterLoginComponent } from '../../app-layout/after-login/after-login.component';


@Component({
  selector: 'app-landing',
  imports: [AfterLoginComponent],
  templateUrl: './landing.component.html',
  styleUrl: './landing.component.scss',
})
export class LandingComponent implements OnInit {
  isLaunchClicked: boolean = false;
  @Input()
  title: string = '';

  ngOnInit(): void {
    // Initialization logic here
  }

  onLaunch(): void {
    this.isLaunchClicked = true;
  }
}
