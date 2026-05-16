import { ErrorHandler, Injectable } from '@angular/core';
import { environment } from '../../../environments/environment';

/**
 * SafeLogger
 * --------------------------------------------------------------
 * Centralised, security-aware logger.
 *
 * Rationale (Infosec finding):
 *   Errors / objects must NEVER be exposed to end users or printed
 *   to the browser console in production because they may carry
 *   sensitive information (tokens, URLs, stack traces, payloads,
 *   PII, internal identifiers, etc.).
 *
 * Behaviour:
 *   - In production builds: every method is a no-op. Nothing is
 *     written to the console regardless of what is passed in.
 *   - In non-production builds: writes a generic label only. The
 *     raw error/object is intentionally NOT forwarded to keep
 *     developer logs free of sensitive payloads as well.
 *
 * Usage:
 *   constructor(private log: SafeLogger) {}
 *   this.log.debug('Failed to load conversations');
 *
 * Do not pass error objects, request/response bodies, tokens,
 * user data or any other potentially sensitive value as additional
 * arguments. The signature deliberately accepts a single message
 * string only.
 */
export class SafeLogger {
  static debug(_message: string): void {
    if (!environment.production) {
      // eslint-disable-next-line no-console
      console.debug(`[app] ${_message}`);
    }
  }

  static warn(_message: string): void {
    if (!environment.production) {
      // eslint-disable-next-line no-console
      console.warn(`[app] ${_message}`);
    }
  }

  /**
   * Records that an error occurred WITHOUT exposing its contents.
   * The raw error object is never logged.
   */
  static error(_message: string): void {
    if (!environment.production) {
      // eslint-disable-next-line no-console
      console.error(`[app] ${_message}`);
    }
  }
}

/**
 * Global Angular error handler.
 *
 * Swallows uncaught errors silently in production so that nothing
 * sensitive ever reaches the browser console. In development it
 * still records a generic marker (no payload) so developers can
 * see that an error occurred and reproduce it via the debugger.
 */
@Injectable()
export class SilentErrorHandler implements ErrorHandler {
  handleError(_error: unknown): void {
    SafeLogger.error('Unhandled application error');
  }
}
