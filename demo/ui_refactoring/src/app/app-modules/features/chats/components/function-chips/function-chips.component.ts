import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ChatStore } from '../../services/chat.store';

export interface MenaFunctionChip {
  code: string;
  label: string;
  full: string;
  icon: string;
}

/** Direct port of menabot-ui's MENA_FUNCTIONS list — the SAME chip set drives /chat. */
export const MENA_FUNCTIONS: MenaFunctionChip[] = [
  { code: 'AWS',     label: 'AWS',     full: 'MENA Administrative and Workplace Services', icon: 'bi-house-door' },
  { code: 'BMC',     label: 'BMC',     full: 'Brand Marketing Communications',              icon: 'bi-megaphone' },
  { code: 'C&I',     label: 'C&I',     full: 'Clients & Industries',                        icon: 'bi-people' },
  { code: 'Finance', label: 'Finance', full: 'Finance Function',                            icon: 'bi-currency-dollar' },
  { code: 'GCO',     label: 'GCO',     full: 'CBS MENA General Counsel Office',             icon: 'bi-building' },
  { code: 'Risk',    label: 'Risk',    full: 'MENA Risk Function',                          icon: 'bi-shield-check' },
  { code: 'SCS',     label: 'SCS',     full: 'Supply Chain Services',                       icon: 'bi-box-seam' },
  { code: 'TME',     label: 'TME',     full: 'Travel, Meetings & Events',                   icon: 'bi-globe' },
  { code: 'Talent',  label: 'Talent',  full: 'Talent',                                       icon: 'bi-person' },
];

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
    if (this.selected() === chip.code) {
      this.chat.clearFunction();
      return;
    }
    this.chat.selectFunction(chip.code);
  }

  trackByCode(_: number, chip: MenaFunctionChip): string {
    return chip.code;
  }
}
