/// <reference types="@angular/localize" />

import { bootstrapApplication } from '@angular/platform-browser';
import { appConfig } from './app/app.config';
import { AppComponent } from './app/app.component';
import { EnvironmentLoader as environmentLoaderPromise } from './environments/environment-loader';
import { environment } from './environments/environment';
import { enableProdMode } from '@angular/core';

environmentLoaderPromise.then((env) => {
  if (environment.production) {
    enableProdMode();
  }
  environment.apiHost = env.apiHost;
  environment.apiUrl = `//${env.apiHost}/`;
  environment.layout = env.layout;
  environment.ccode = env.ccode;
  environment.tcode = env.tcode;
  console.log('Loaded environment', environment);

  bootstrapApplication(AppComponent, appConfig).catch((err) =>
    console.error(err)
  );
});
