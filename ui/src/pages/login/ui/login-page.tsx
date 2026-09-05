import { Navigate, useNavigate } from 'react-router';
import { useSessionExpired, useSessionToken } from '@/entities/session';
import { LoginForm } from '@/features/auth';
import { Callout } from '@/shared/ui';
import styles from './login-page.module.css';

export function LoginPage() {
  const token = useSessionToken();
  const expired = useSessionExpired();
  const navigate = useNavigate();

  // Вошедшему на экране входа делать нечего.
  if (token !== null) return <Navigate to="/tasks" replace />;

  return (
    <main className={styles.screen}>
      <div className={styles.card}>
        <div>
          <h1 className={styles.title}>Трекер</h1>
          <p className={styles.subtitle}>
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
