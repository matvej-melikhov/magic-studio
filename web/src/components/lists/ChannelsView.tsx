import { useState } from 'react';
import { useAppState } from '../../store/appState';
import { api } from '../../api/client';
import { toast } from '../../store/toast';

export default function ChannelsView() {
  const { channels, refresh } = useAppState();
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);

  const add = async () => {
    const username = input.trim();
    if (!username) return;
    setBusy(true);
    const resp = await api('/api/channels/add', { username });
    setBusy(false);
    if (resp.ok) {
      setInput('');
      toast('Канал подключён');
      void refresh();
    } else toast(resp.error || 'Ошибка', true);
  };

  const remove = async (username: string) => {
    if (!confirm('Отключить канал ' + username + '?')) return;
    await api('/api/channels/remove', { username });
    void refresh();
  };

  return (
    <section className="view active" id="view-channels">
      <div className="page">
        <h2>Каналы</h2>
        <div className="add-row">
          <input id="channelInput" placeholder="@username канала" autoCapitalize="off"
            value={input} onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') void add(); }} />
          <button className="btn primary" id="addChannelBtn" disabled={busy}
            onClick={() => void add()}>Подключить</button>
        </div>
        <div id="channelsList">
          {!channels.length ? (
            <div className="empty-state">
              Каналы не подключены.<br />
              Добавьте бота администратором канала и укажите его @username выше.
            </div>
          ) : (
            channels.map((c) => (
              <div key={c.username} className="card">
                <div className="body">
                  <div className="title">{c.title}</div>
                  <div className="meta">{c.username}</div>
                </div>
                <button className="del" onClick={() => void remove(c.username)}>Отключить</button>
              </div>
            ))
          )}
        </div>
        <p className="hint">
          Добавьте бота администратором канала с правом «Публикация сообщений»,
          затем укажите здесь @username канала. Приватные каналы без публичной
          ссылки пока не поддерживаются.
        </p>
      </div>
    </section>
  );
}
