import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';
import { PromptOption } from '../../models/chat.model';

/**
 * Horizontal "drill down" chip strip rendered below an assistant bubble when
 * the SSE `drill_suggestions` event arrives. Clicking a chip submits the
 * associated prompt as the next user message.
 */
@Component({
  selector: 'app-drill-chips',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './drill-chips.component.html',
  styleUrl: './drill-chips.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class DrillChipsComponent {
  suggestions = input.required<PromptOption[]>();
  picked = output<PromptOption>();

  onClick(opt: PromptOption): void {
    this.picked.emit(opt);
  }
}
