import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ChatService } from '../../services/chat.service';

interface MenaFunctionChip {
  code: string;
  label: string;
  full: string;        // full description shown in tooltip + selected pill
  icon: string;
  /** CSS variable holding this chip's accent color (image-3 palette). */
  colorVar: string;
}

export const MENA_FUNCTIONS: MenaFunctionChip[] = [
  { code: 'AWS',     label: 'AWS',     full: 'MENA Administrative and Workplace Services', icon: 'home',      colorVar: '--fn-aws' },
  { code: 'BMC',     label: 'BMC',     full: 'Brand Marketing Communications',              icon: 'megaphone', colorVar: '--fn-bmc' },
  { code: 'C&I',     label: 'C&I',     full: 'Clients & Industries',                        icon: 'user-plus', colorVar: '--fn-ci' },
  { code: 'Finance', label: 'Finance', full: 'Finance Function',                            icon: 'dollar',    colorVar: '--fn-finance' },
  { code: 'GCO',     label: 'GCO',     full: 'CBS MENA General Counsel Office',             icon: 'building',  colorVar: '--fn-gco' },
  { code: 'Risk',    label: 'Risk',    full: 'MENA Risk Function',                          icon: 'shield',    colorVar: '--fn-risk' },
  { code: 'SCS',     label: 'SCS',     full: 'Supply Chain Services',                       icon: 'box',       colorVar: '--fn-scs' },
  { code: 'TME',     label: 'TME',     full: 'Travel, Meetings & Events',                   icon: 'globe',     colorVar: '--fn-tme' },
  { code: 'Talent',  label: 'Talent',  full: 'Talent',                                       icon: 'person',    colorVar: '--fn-talent' },
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
  private readonly chat = inject(ChatService);

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
