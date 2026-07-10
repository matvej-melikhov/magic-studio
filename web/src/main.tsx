import React from 'react';
import ReactDOM from 'react-dom/client';
import { RouterProvider, createBrowserRouter, Navigate } from 'react-router-dom';
import App from './App';

/* Стенды живут под префиксами /dev/ и /prod/ (nginx отрезает префикс
   до server.py, но URL в браузере его содержит) — роутеру нужен basename.
   Эвристика совпадает с LS_SEG из editor.html. */
const seg = location.pathname.split('/')[1];
const basename = seg === 'dev' || seg === 'prod' ? `/${seg}` : '/';

const router = createBrowserRouter(
  [
    {
      path: '/',
      element: <App />,
      children: [
        { index: true, element: <Navigate to="/editor" replace /> },
        { path: 'editor', element: <div>Редактор (фаза 2)</div> },
        { path: 'drafts', element: <div>Черновики (фаза 1)</div> },
        { path: 'scheduled', element: <div>Посты (фаза 1)</div> },
        { path: 'channels', element: <div>Каналы (фаза 1)</div> },
      ],
    },
  ],
  { basename },
);

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <RouterProvider router={router} />
  </React.StrictMode>,
);
