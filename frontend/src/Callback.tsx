import { useHandleSignInCallback } from '@logto/react';

export default function Callback() {
  useHandleSignInCallback(() => {
    window.location.replace('/');
  });
  return (
    <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh' }}>
      <p>登录中…</p>
    </div>
  );
}
