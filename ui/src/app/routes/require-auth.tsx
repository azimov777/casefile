import { Navigate, Outlet } from 'react-router';
import { useSessionToken, useTokenPending } from '@/entities/session';

/**
 * Без ключа дальше не пускаем. Ключей два источника: конфигурация установки и токен,
 * введённый человеком (`src/shared/api/token.ts`). Токен сбрасывает перехватчик `401`,
 * подписка на смену значения перерисовывает страж — поэтому просроченный сеанс уводит
 * на вход сам, с какого бы экрана ни пришёл отказ.
 *
 * Пока установку про ключ ещё спрашивают, страж ждёт и не рисует ничего. Уводить
 * на вход в этот момент нельзя: локальный человек, которому ключ отдаёт установка,
 * получал бы вспышку чужого экрана при каждой загрузке. Рисовать вместо ожидания
 * заглушку тоже незачем — конфигурацию читают до первой отрисовки (`src/main.tsx`),
 * и в браузере этого состояния не видно вовсе.
 */
export function RequireAuth() {
  const pending = useTokenPending();
  const token = useSessionToken();

  if (pending) return null;
  if (token === null) return <Navigate to="/login" replace />;
  return <Outlet />;
}
