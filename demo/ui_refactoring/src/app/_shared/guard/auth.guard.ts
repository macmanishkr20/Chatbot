import { inject } from '@angular/core';
import { Router, type CanActivateFn } from '@angular/router';
import { AuthService } from '../messaging-service/auth.service';

export const authGuard: CanActivateFn = (route, state) => {
  const authService = inject(AuthService);
  const router = inject(Router);

  const url = state.url;
  const module = route.data['key'];
  // console.log('module', url, '|', module);
  if (!module) {
    console.warn('Module key is not defined in the route data');
    return false;
  }

  if (JSON.stringify(authService.user) === JSON.stringify({})) {
    router.navigate([''], { queryParams: { returnUrl: url } });
    return false;
  }

  const index = authService.user.modules.findIndex((v, i) => {
    return (
      v.key.toLowerCase() === 'module' &&
      v.value.toLowerCase() === module.toLowerCase()
    );
  });

  if (index === -1) {
    router.navigate(['denied']);
    return false;
  }

  if (index > -1 && authService.user.isAuthenticated) {
    return true;
  }

  router.navigate([''], { queryParams: { returnUrl: url } });
  return false;
};
