import { MenaFunctionChip } from "../models/mena-function-chip";

/** Direct port of menabot-ui's MENA_FUNCTIONS list — the SAME chip set drives /chat. */
export const MENA_FUNCTIONS: MenaFunctionChip[] = [
  { code: 'AWS',     label: 'AWS', title:'MENA Administrative and Workplace Services',     full: 'MENA Administrative and Workplace Services', icon: 'bi-house-door' },
  { code: 'BMC',     label: 'BMC', title:'Brand, Market & Communications',     full: 'Brand Marketing Communications',              icon: 'bi-megaphone' },
  { code: 'C&I',     label: 'C&I', title:'Clients & Industries',     full: 'Clients & Industries',                        icon: 'bi-people' },
  { code: 'Finance', label: 'Finance', title:'Finance', full: 'Finance Function',                            icon: 'bi-currency-dollar' },
  { code: 'GCO',     label: 'GCO', title:'CBS MENA General Counsel Office',     full: 'CBS MENA General Counsel Office',             icon: 'bi-building' },
  { code: 'Risk',    label: 'Risk', title:'MENA Risk Function',    full: 'MENA Risk Function',                          icon: 'bi-shield-check' },
  { code: 'SCS',     label: 'SCS', title:'Supply Chain Services',     full: 'Supply Chain Services',                       icon: 'bi-box-seam' },
  { code: 'Talent',  label: 'Talent', title:'Talent',  full: 'Talent',                                       icon: 'bi-person' },
  { code: 'TME',     label: 'TME', title:'Travel, Meetings & Events',     full: 'Travel, Meetings & Events',                   icon: 'bi-globe' },
];