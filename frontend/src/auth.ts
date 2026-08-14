import { LogtoConfig } from '@logto/react';

const endpoint = import.meta.env.VITE_LOGTO_ENDPOINT;
const appId = import.meta.env.VITE_LOGTO_APP_ID;

if (!endpoint || !appId) {
  // eslint-disable-next-line no-console
  console.warn('Logto env missing: VITE_LOGTO_ENDPOINT / VITE_LOGTO_APP_ID');
}

export const logtoConfig: LogtoConfig = {
  endpoint: endpoint ?? '',
  appId: appId ?? '',
  scopes: ['openid', 'profile', 'email'],
};

export function callbackUri(origin: string): string {
  return `${origin}/callback`;
}

export function postLogoutRedirectUri(origin: string): string {
  return `${origin}/`;
}
