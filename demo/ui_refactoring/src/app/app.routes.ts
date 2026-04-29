import { Routes } from '@angular/router';
import { SigninOidcComponent } from './_shared/components/signin-oidc/signin-oidc.component';
import { PermissionDeniedComponent } from './_shared/components/permission-denied/permission-denied.component';
import { NotFoundComponent } from './_shared/components/not-found/not-found.component';
import { BeforeLoginComponent } from './app-layout/before-login/before-login.component';
export const routes: Routes = [
  { path: '', component: SigninOidcComponent },
  { path: 'signin-oidc', component: SigninOidcComponent },
  { path: 'logoff', component: BeforeLoginComponent },
  {
    path: 'settings',
    loadChildren: () => import('./app-modules/settings/settings.route')
      .then(m => m.SETTING_ROUTES)
  },
  {
    path: 'features',
    loadChildren: () => import('./app-modules/features/feature.routes')
      .then(m => m.FEATURE_ROUTES)
  },
  { path: 'denied', component: PermissionDeniedComponent },
  { path: 'notfound', component: NotFoundComponent },
  { path: '**', redirectTo: 'notfound' },
];
