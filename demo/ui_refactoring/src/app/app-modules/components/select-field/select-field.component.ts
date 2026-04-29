import { Component, EventEmitter, Input, Output, type OnInit } from '@angular/core';
import { NgSelectModule } from '@ng-select/ng-select';

@Component({
  selector: 'app-select-field',
  imports: [NgSelectModule],
  templateUrl: './select-field.component.html',
  styleUrl: './select-field.component.scss',
})
export class SelectFieldComponent implements OnInit {
  @Input() label: string = '';

  @Input() items: any[] = [];
  @Input() bindLabel: string = 'name';
  @Input() placeholder: string = 'Select an option';
  @Input() searchable: boolean = true;
  @Input() clearable: boolean = false;
  @Output() selectionChanged = new EventEmitter<any>();

  onSelectionChange(event: any) {
    this.selectionChanged.emit(event);
  }

  ngOnInit(): void { }

}
