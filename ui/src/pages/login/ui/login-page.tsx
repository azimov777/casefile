import { Navigate, useNavigate } from 'react-router';
import { useSessionExpired, useSessionToken } from '@/entities/session';
import { LoginForm } from '@/features/auth';
import { Callout } from '@/shared/ui';

export function LoginPage() {
  const token = useSessionToken();
  const expired = useSessionExpired();
  const navigate = useNavigate();

  // Вошедшему на экране входа делать нечего.
  if (token !== null) return <Navigate to="/tasks" replace />;

  return (
    /*
     * Карточка прижата к верху (`items-start` плюс верхний отступ), а не центрирована:
     * центрирование по вертикали означает, что каждая появившаяся строка — сообщение
     * об отказе, объяснение просроченного сеанса — двигает вверх всё, включая кнопку,
     * в которую человек целится (замерено: 508 → 477 пикселей). Прижатая сверху карточка
     * растёт только вниз (выявлено при обзоре задачи 01).
     *
     * Отступ задан `clamp`, а не одним шагом сетки: на низком окне карточка не должна
     * уезжать за нижний край, на высоком — стоять под самой кромкой. Края взяты шагами
     * сетки; у доли высоты окна своего токена нет и быть не может.
     */
    <main className="flex min-h-full items-start justify-center px-4 pt-[clamp(calc(var(--spacing)*8),18vh,calc(var(--spacing)*48))] pb-8">
      <div className="flex w-full max-w-112 flex-col gap-6 rounded-control border border-line bg-surface p-8">
        <div>
          <h1 className="text-title">Трекер</h1>
          <p className="mt-1 text-meta text-muted">
            Наблюдение за задачами, которые ведут агенты, и ответы на их вопросы.
          </p>
        </div>

        {expired ? (
          <Callout tone="danger">
            Сеанс закончился: сервер больше не принимает сохранённый токен. Введите токен заново.
          </Callout>
        ) : null}

        <LoginForm onSuccess={() => void navigate('/tasks', { replace: true })} />
      </div>
    </main>
  );
}
