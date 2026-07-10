import React from 'react';
import ReactDOM from 'react-dom/client';
import { RouterProvider, createBrowserRouter, Navigate } from 'react-router-dom';
import App from './App';
import DraftsView from './components/lists/DraftsView';
import ScheduledView from './components/lists/ScheduledView';
import ChannelsView from './components/lists/ChannelsView';

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
        {
          path: 'editor',
          element: (
            <section className="view active" id="view-editor">
              <div className="page"><h2>Редактор</h2>
                <div className="empty-state">Переносится в фазе 2</div>
              </div>
            </section>
          ),
        },
        { path: 'drafts', element: <DraftsView /> },
        { path: 'scheduled', element: <ScheduledView /> },
        { path: 'channels', element: <ChannelsView /> },
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
