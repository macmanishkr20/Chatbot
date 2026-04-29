import { Routes } from "@angular/router";
import { authGuard } from "../../../_shared/guard/auth.guard";

export const ADMIN_ROUTES: Routes = [
    {
        path: '',
        loadComponent: () => import('./master/master.component')
            .then(m => m.MasterComponent),
        children: [
            { path: '', redirectTo: 'dashboard', pathMatch: 'full' },
            {
                path: 'dashboard',
                loadComponent: () => import('./pages/dashboard/dashboard.component')
                    .then(m => m.DashboardComponent),
                canActivate: [authGuard],
                data: { key: 'setting_access' },
            },
            {
                path: 'user-management',
                loadComponent: () => import('./pages/user-management/user-management.component')
                    .then(m => m.UserManagementComponent),
                canActivate: [authGuard],
                data: { key: 'setting_access' },
            }
        ]
    }
];