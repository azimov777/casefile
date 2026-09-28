import { useQuery } from '@tanstack/react-query';
import { Navigate } from 'react-router';
import { bootstrapQueryOptions } from '@/entities/session';

/**
 * `/`: пока состояние знакомства учётной записи — `pending`, ведёт на «Начало»
 * (`TRK-361`, `TRK-360#17`); во всех остальных случаях, ключ без учётной записи
 * включённый, — на список задач, как и раньше.
 *
 * Ждёт первый кадр `bootstrap`, не рисуя ничего, — тем же приёмом, что `RequireAuth`
 * ждёт ответ про ключ (`require-auth.tsx`): экран, мелькнувший списком задач и тут же
 * сменившийся «Началом», был бы хуже короткого ожидания.
 */
export function HomeRedirect() {
  const bootstrap = useQuery(bootstrapQueryOptions());

  if (bootstrap.isPending) return null;

  const pending = bootstrap.data?.account?.onboarding.status === 'pending';
  return <Navigate to={pending ? '/start' : '/tasks'} replace />;
}
