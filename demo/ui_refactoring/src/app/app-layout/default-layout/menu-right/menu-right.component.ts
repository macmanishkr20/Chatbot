
import { Component, Input, type OnInit } from '@angular/core';
import { RouterModule } from '@angular/router';
import { MenuItem } from '../../../_shared/models/menu-item';
import { NgbDropdownModule } from '@ng-bootstrap/ng-bootstrap';

@Component({
  selector: 'app-menu-right',
  imports: [RouterModule, NgbDropdownModule],
  templateUrl: './menu-right.component.html',
  styleUrl: './menu-right.component.scss',
})
export class MenuRightComponent implements OnInit {
  @Input()
  menus: MenuItem[] = [];

  ngOnInit(): void {}
}
