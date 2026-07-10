import { useState } from 'react';
import { useSession } from '../store/session';

/* Окно входа: deep-link на бота + фоновый опрос, код — запасной путь.
   Разметка и id из editor.html (#login.open управляет видимостью в CSS). */
export default function LoginModal() {
  const s = useSession();
  const [code, setCode] = useState('');

  return (
    <div id="login" className={s.loginOpen ? 'open' : ''}>
      <div className="panel">
        <div className="logo-big">Md</div>
        <h3>Вход в студию постов</h3>
        <p>Нажмите кнопку — откроется чат с ботом, вход подтвердится автоматически.</p>
        <a className="btn primary" id="tgLoginBtn" target="_blank" rel="noopener"
          href={s.botLink} onClick={() => s.startPoll()}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M23.9 3.4c.2-1.2-1-2.2-2.1-1.7L1.4 10.2c-1.2.5-1.1 2.3.2 2.6l5.5 1.4 2.1 6.6c.4 1.1 1.8 1.4 2.6.5l3-3.3 5.5 4c1 .8 2.5.2 2.7-1.1zM8.8 13.6l9.4-7.7c.3-.2.6.2.4.5l-7.6 8.5-.3 3.4z"/></svg>
          {' '}Войти через Telegram
        </a>
        <p className="wait" id="loginWait" hidden={!s.loginWaiting}>Ждём подтверждения в Telegram…</p>
        <details className="alt">
          <summary>Войти по коду</summary>
          <p>Отправьте боту команду <code>/login</code> и введите код:</p>
          <input id="loginCode" inputMode="numeric" autoComplete="one-time-code"
            maxLength={6} placeholder="······" value={code}
            onChange={(e) => setCode(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') void s.loginWithCode(code.trim()); }} />
          <button className="btn ghost" id="loginBtn"
            onClick={() => void s.loginWithCode(code.trim())}>Войти</button>
        </details>
        <p className="err" id="loginError">{s.loginError}</p>
      </div>
    </div>
  );
}
