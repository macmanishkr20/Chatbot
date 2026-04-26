import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ChatService } from '../../services/chat.service';

interface MenaFunctionChip {
  code: string;
  label: string;
  description: string;
  icon: string;
}

const MENA_FUNCTIONS: MenaFunctionChip[] = [
  { code: 'AWS',     label: 'AWS',     description: 'Administrative & Workplace Services', icon: 'home' },
  { code: 'BMC',     label: 'BMC',     description: 'Brand Marketing Communications',      icon: 'megaphone' },
  { code: 'C&I',     label: 'C&I',     description: 'Clients & Industries',                 icon: 'user-plus' },
  { code: 'Finance', label: 'Finance', description: 'Finance Function',                     icon: 'dollar' },
  { code: 'GCO',     label: 'GCO',     description: 'General Counsel Office',               icon: 'building' },
  { code: 'Risk',    label: 'Risk',    description: 'MENA Risk Function',                   icon: 'shield' },
  { code: 'SCS',     label: 'SCS',     description: 'Supply Chain Services',                icon: 'box' },
  { code: 'TME',     label: 'TME',     description: 'Travel, Meetings & Events',            icon: 'globe' },
  { code: 'Talent',  label: 'Talent',  description: 'Talent / People',                      icon: 'person' },
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

  onPick(chip: MenaFunctionChip): void {
    this.chat.selectFunction(chip.code);
  }

  trackByCode(_: number, chip: MenaFunctionChip): string {
    return chip.code;
  }
}
