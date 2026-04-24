export const environment = {
  production: false,
  apiBaseUrl: 'http://localhost:8000',
  /** Shared secret required on the screenshare WebSocket query string.
   *  Must match SCREENSHARE_SESSION_TOKEN in the backend .env. */
  screenshareToken: 'local-dev-token',
};
