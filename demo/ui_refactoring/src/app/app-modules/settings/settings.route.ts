import { Routes } from '@angular/router';
import { MasterComponent } from './master/master.component';
import { authGuard } from '../../_shared/guard/auth.guard';
import { AccessControlComponent } from './pages/access-control/access-control.component';

export const SETTING_ROUTES: Routes = [
  {
    path: '',
    component: MasterComponent,
    // canActivate: [AuthGuard],
    children: [
      { path: '', redirectTo: 'access', pathMatch: 'full' },
      {
        path: 'access',
        canActivate: [authGuard],
        component: AccessControlComponent,
        data: { key: 'setting_access' },
      },
    ],
  },
];
