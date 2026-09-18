import { useId, useState, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { ApiError } from '@/shared/api';
import { errorMessage } from '@/shared/errors';
import { Button, Callout, Input } from '@/shared/ui';
import { usePasswordLogin } from '../model/use-password-login';

interface PasswordFormProps {
  /** Куда идти после удачного входа — знает страница, а не форма. */
  onSuccess: () => void;
}

/**
 * Вход паролем владельца: одно поле, без имени — пароль у установки один (`TRK-90`).
 *
 * Раскладка та же, что у формы токена (`login-form.tsx`), и по той же причине отказ стоит
 * после кнопки: появившись между полем и кнопкой, он сдвигал бы кнопку под курсором.
 */
export function PasswordForm({ onSuccess }: PasswordFormProps) {
  const [password, setPassword] = useState('');
  const login = usePasswordLogin();
  const inputId = useId();
  const hintId = useId();
  const { t } = useTranslation('login');

  const failed = login.error !== null && login.error !== undefined;

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (password === '') return;
    login.mutate(password, { onSuccess });
  }

  /*
   * Два отказа объясняются словами экрана входа, а не общим словарём ошибок. `401` здесь
   * значит «пароль не подошёл», а словарь по коду `unauthorized` говорит о токене. Окно
   * попыток называет секунды из `details.retry_after` — общий текст их не знает.
   */
  function refusal(error: Error): string {
    if (error instanceof ApiError && error.code === 'unauthorized') return t('passwordWrong');
    if (error instanceof ApiError && error.code === 'password_attempts_exceeded') {
      const seconds = Number(error.details.retry_after);
      if (Number.isFinite(seconds)) return t('passwordThrottled', { seconds });
    }
    return errorMessage(error);
  }

  return (
    <form className="flex flex-col gap-4" onSubmit={submit} noValidate>
      <div className="flex flex-col gap-2">
        <label className="font-semibold" htmlFor={inputId}>
          {t('passwordLabel')}
        </label>
        <Input
          id={inputId}
          type="password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          autoComplete="current-password"
          spellCheck={false}
          aria-invalid={failed}
          aria-describedby={hintId}
        />
        <span className="text-meta text-muted" id={hintId}>
          {t('passwordHint')}
        </span>
      </div>

      <div>
        <Button type="submit" disabled={login.isPending || password === ''}>
          {login.isPending ? t('submitting') : t('submit')}
        </Button>
      </div>

      {failed ? <Callout tone="danger">{refusal(login.error)}</Callout> : null}
    </form>
  );
}
