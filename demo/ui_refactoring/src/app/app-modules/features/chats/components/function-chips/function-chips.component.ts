import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ChatStore } from '../../services/chat.store';
import { MenaFunctionChip } from '../../../../../_shared/models/mena-function-chip';
import { MENA_FUNCTIONS } from '../../../../../_shared/constants/mena-function';


@Component({
  selector: 'app-function-chips',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './function-chips.component.html',
  styleUrl: './function-chips.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class FunctionChipsComponent {
  private readonly chat = inject(ChatStore);

  readonly chips = MENA_FUNCTIONS;
  readonly selected = this.chat.selectedFunction;
  readonly highlighted = this.chat.chipsHighlighted;
  readonly reason = this.chat.functionPromptReason;

  readonly hasSelection = computed(() => !!this.selected());

  /** Toggle: clicking the active chip deselects it. */
  onPick(chip: MenaFunctionChip): void {
    if(this.chat.isStreaming()) {
      return; 
    }
    if (this.selected() === chip.code) {
      this.chat.clearFunction();
      return;
    }
    this.chat.selectFunction(chip.code);
  }

  trackByCode(_: number, chip: MenaFunctionChip): string {
    return chip.code;
  }

  isStreaming(): boolean {
    return this.chat.isStreaming();
  }
}
