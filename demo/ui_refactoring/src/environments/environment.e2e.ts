export const environment = {
  production: false,
  msalConfig: {
    auth: {
      clientId: '',
      authority: 'https://login.windows-ppe.net/common',
    },
  },
  apiConfig: {
    scopes: ['user.read'],
    uri: 'https://graph.microsoft-ppe.com/v1.0/me',
  },
};
