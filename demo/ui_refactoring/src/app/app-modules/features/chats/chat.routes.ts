import { Routes } from "@angular/router";
import { authGuard } from "../../../_shared/guard/auth.guard";

export const CHAT_ROUTES: Routes = [
    {
        path: '',
        loadComponent: () => import('./master/master.component')
            .then(m => m.MasterComponent),
        children: [
            {
                path: '',
                loadComponent: () => import('./pages/chat-container/chat-container.component')
                    .then(m => m.ChatContainerComponent),
                canActivateChild: [authGuard],
                data: { key: 'setting_access' },
                children: [
                    {
                        path: '',
                        loadComponent: () => import('./components/chat-window/chat-window.component')
                            .then(m => m.ChatWindowComponent),
                        canActivate: [authGuard],
                        data: { key: 'setting_access' },
                    },
                    {
                        path: ':id',
                        loadComponent: () => import('./components/chat-window/chat-window.component')
                            .then(m => m.ChatWindowComponent),
                        canActivate: [authGuard],
                        data: { key: 'setting_access' },
                    }
                ]
            }
        ]
    },
];