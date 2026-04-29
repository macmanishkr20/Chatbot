import { Routes } from "@angular/router";
import { authGuard } from "../../_shared/guard/auth.guard";

export const FEATURE_ROUTES: Routes = [
    {
        path: '',
        loadComponent: () => import('./master/master.component')
            .then(m => m.MasterComponent),
        children: [
            {
                path: '',
                redirectTo: 'home',
                pathMatch: 'full'
            },
            {
                path: 'home',
                loadComponent: () => import('./pages/home/home.component')
                    .then(m => m.HomeComponent),
                canActivate: [authGuard],
                data: { key: 'setting_access', },
            },
            {
                path: 'page',
                loadComponent: () => import('./pages/lay-out/lay-out.component')
                    .then(m => m.LayOutComponent),
                canActivate: [authGuard],
                data: { key: 'setting_access', },
                children: [
                    {
                        path: '', redirectTo: 'chats', pathMatch: 'full'
                    },
                    {
                        path: 'chats',
                        loadChildren: () => import('./chats/chat.routes')
                            .then(m => m.CHAT_ROUTES),
                    },
                    {
                        path: 'admin',
                        loadChildren: () => import('./admin/admin.routes')
                            .then(m => m.ADMIN_ROUTES),
                    }
                ]
            }
        ]
    },
];