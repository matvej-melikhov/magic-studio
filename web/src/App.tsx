import { Outlet } from 'react-router-dom';

/* Оболочка приложения: в фазе 1 здесь появятся сайдбар и мобильная
   навигация, пока — только контейнер для разделов. */
export default function App() {
  return <Outlet />;
}
