
/// This file defines the MenaFunctionChip interface and the MENA_FUNCTIONS constant, which is a list of function chips used in the chat application. Each chip has a code, label, full name, and icon. The chips are used to filter or categorize chat queries based on different MENA functions.
export interface MenaFunctionChip {
  code: string;
  label: string;
  full: string;
  icon: string;
  title?: string;
}