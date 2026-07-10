import { useEffect, useState } from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import Sidebar, { applySavedCollapse } from './components/Sidebar';
import MobileTopBar from './components/MobileTopBar';
import LoginModal from './components/LoginModal';
import Toast from './components/Toast';
import { useAppState } from './store/appState';
import { lsStore } from './lib/lsStore';
import './styles/app.css';

export default function App() {
  const [collapsed, setCollapsed] = useState(applySavedCollapse);
  const location = useLocation();
  const refresh = useAppState((s) => s.refresh);

  /* Как в editor.html: при заходе и при переходе в списочные разделы
     подтягиваем состояние с сервера (заодно 401 откроет окно входа) */
  useEffect(() => {
    void refresh();
  }, [location.pathname, refresh]);

  const toggleSidebar = () => {
    setCollapsed((c) => {
      lsStore.set('sideCollapsed', c ? '0' : '1');
      return !c;
    });
  };

  return (
    <div id="app" className={collapsed ? 'side-collapsed' : ''}>
      <Sidebar onToggle={toggleSidebar} />
      <div id="content">
        <MobileTopBar />
        <Outlet />
      </div>
      <LoginModal />
      <Toast />
    </div>
  );
}
