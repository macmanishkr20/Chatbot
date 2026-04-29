
import { Component, Input, type OnInit } from '@angular/core';
import { RouterModule } from '@angular/router';
import { MenuItem } from '../../../_shared/models/menu-item';
import { NgbDropdownModule } from '@ng-bootstrap/ng-bootstrap';

@Component({
  selector: 'app-menu-left',
  imports: [RouterModule, NgbDropdownModule],
  templateUrl: './menu-left.component.html',
  styleUrl: './menu-left.component.scss',
})
export class MenuLeftComponent implements OnInit {
  @Input()
  menus: MenuItem[] = [];

  ngOnInit(): void {}
}
