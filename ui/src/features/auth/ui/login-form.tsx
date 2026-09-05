import { useId, useState, type FormEvent } from 'react';
import { errorMessage } from '@/shared/errors';
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

      <div>
        <Button type="submit" disabled={login.isPending || token.trim() === ''}>
          {login.isPending ? 'Проверяем…' : 'Войти'}
        </Button>
      </div>

      {/*
       * Сообщение об отказе стоит после кнопки, а не перед ней: между подсказкой
       * и кнопкой оно сдвигало кнопку вниз ровно в тот момент, когда человек в неё
       * целился, — и второй клик попадал мимо (выявлено при обзоре задачи 01).
       * Программе чтения с экрана порядок не мешает: `Callout` объявляет отказ сам.
       */}
      {failed ? <Callout tone="danger">{errorMessage(login.error)}</Callout> : null}
    </form>
  );
}
