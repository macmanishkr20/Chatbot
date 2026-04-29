export class ServiceResult<T> {
  hasErrors: boolean = false;
  errors: string[] = [];
  success: boolean = false;
  result: T | undefined;
  successMessage: string[] = [];
}
