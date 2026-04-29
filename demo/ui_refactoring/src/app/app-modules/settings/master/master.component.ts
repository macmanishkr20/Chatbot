import { CommonModule } from '@angular/common';
import { Component, type OnInit } from '@angular/core';
import { RouterModule } from '@angular/router';

@Component({
  selector: 'app-master',
  imports: [CommonModule, RouterModule],
  templateUrl: './master.component.html',
  styleUrl: './master.component.scss',
})
export class MasterComponent implements OnInit {
  ngOnInit(): void {}
}
