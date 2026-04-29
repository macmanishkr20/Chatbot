export const environment = {
  production: false,
  msalConfig: {
    auth: {
      clientId: '',
      authority: 'https://login.microsoftonline.com/common',
    },
  },
  apiConfig: {
    scopes: ['user.read'],
    uri: 'https://graph.microsoft.com/v1.0/me',
  },
};
