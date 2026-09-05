import { useId, useState, type FormEvent } from 'react';
import { ApiError } from '@/shared/api';
import { errorText } from '@/shared/errors';
import { Button, Callout } from '@/shared/ui';
import { useLogin } from '../model/use-login';
import styles from './login-form.module.css';

interface LoginFormProps {
  /** Куда идти после удачного входа — знает страница, а не форма. */
  onSuccess: () => void;
}

export function LoginForm({ onSuccess }: LoginFormProps) {
  const [token, setToken] = useState('');
  const login = useLogin();
  const inputId = useId();
  const hintId = useId();

  const failed = login.error !== null && login.error !== undefined;

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (token.trim() === '') return;
    login.mutate(token, { onSuccess });
  }

  return (
    <form className={styles.form} onSubmit={submit} noValidate>
      <div className={styles.field}>
        <label className={styles.label} htmlFor={inputId}>
          Токен участника
        </label>
        <input
          id={inputId}
          className={styles.input}
          type="password"
          value={token}
          onChange={(event) => setToken(event.target.value)}
          autoComplete="off"
          spellCheck={false}
          aria-invalid={failed}
          aria-describedby={hintId}
          placeholder="trk_..."
        />
        <span className={styles.hint} id={hintId}>
          Токен печатает <code>docker compose run --rm init</code> в репозитории бэкенда. Он
          хранится только в этом браузере и уходит на сервер заголовком.
        </span>
      </div>

      {failed ? <Callout tone="danger">{describe(login.error)}</Callout> : null}

      <div>
        <Button type="submit" disabled={login.isPending || token.trim() === ''}>
          {login.isPending ? 'Проверяем…' : 'Войти'}
        </Button>
      </div>
    </form>
  );
}

function describe(error: unknown): string {
  if (error instanceof ApiError) return errorText(error.code, error.message);
  return error instanceof Error ? error.message : 'Неизвестная ошибка.';
}
