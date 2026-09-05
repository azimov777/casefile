import { Navigate, Outlet } from 'react-router';
import { useSessionToken } from '@/entities/session';

/**
 * Без токена дальше не пускаем. Токен сбрасывает перехватчик `401`, подписка на смену
 * значения перерисовывает страж — поэтому просроченный сеанс уводит на вход сам,
 * с какого бы экрана ни пришёл отказ.
 */
export function RequireAuth() {
  const token = useSessionToken();

  if (token === null) return <Navigate to="/login" replace />;
  return <Outlet />;
}
