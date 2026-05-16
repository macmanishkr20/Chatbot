/// <reference types="@angular/localize" />

import { bootstrapApplication } from '@angular/platform-browser';
import { CSP_NONCE } from '@angular/core';
import { appConfig } from './app/app.config';
import { AppComponent } from './app/app.component';
import { EnvironmentLoader as environmentLoaderPromise } from './environments/environment-loader';
import { environment } from './environments/environment';
import { enableProdMode } from '@angular/core';

/**
 * Read CSP nonce from meta tag injected by server
 * Angular will use this nonce for all dynamically created style tags
 */
function getCspNonce(): string {
  const nonceMetaTag = document.querySelector('meta[name="csp-nonce"]');
  const nonce = nonceMetaTag?.getAttribute('content') || '';
  
  if (!nonce) {
    console.warn('CSP nonce not found in meta tag. Dynamic styles may be blocked by CSP.');
  }
  
  return nonce;
}

environmentLoaderPromise.then((env) => {
  if (environment.production) {
    enableProdMode();
  }
  environment.apiHost = env.apiHost;
  environment.apiUrl = `//${env.apiHost}/`;
  environment.layout = env.layout;
  environment.ccode = env.ccode;
  environment.tcode = env.tcode;
  console.log('Loaded environment');

  // Configure Angular with CSP nonce provider
  const configWithCsp = {
    ...appConfig,
    providers: [
      ...(appConfig.providers || []),
      {
        provide: CSP_NONCE,
        useFactory: getCspNonce
      }
    ]
  };

  bootstrapApplication(AppComponent, configWithCsp).catch((err) => {
      // Bootstrap errors are handled internally. Nothing about the
      // underlying error is exposed to the user or console.
});
});

