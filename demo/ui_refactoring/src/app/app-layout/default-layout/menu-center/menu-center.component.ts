
import { Component, Input, type OnInit } from '@angular/core';
import { RouterModule } from '@angular/router';
import { MenuItem } from '../../../_shared/models/menu-item';
import { NgbDropdownModule } from '@ng-bootstrap/ng-bootstrap';

@Component({
  selector: 'app-menu-center',
  imports: [RouterModule, NgbDropdownModule],
  templateUrl: './menu-center.component.html',
  styleUrl: './menu-center.component.scss',
})
export class MenuCenterComponent implements OnInit {
  @Input()
  menus: MenuItem[] = [];

  ngOnInit(): void {}
}
