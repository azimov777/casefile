import { useId, useState, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { ApiError } from '@/shared/api';
import { errorMessage } from '@/shared/errors';
import { Button, Callout, Input } from '@/shared/ui';
import { useAccountLogin } from '../model/use-account-login';

interface AccountLoginFormProps {
  /** Куда идти после удачного входа — знает страница, а не форма. */
  onSuccess: () => void;
}

/**
 * Вход учётной записью: почта и пароль (`TRK-113`).
 *
 * Раскладка та же, что у формы токена (`login-form.tsx`), и по той же причине отказ стоит
 * после кнопки: появившись между полями и кнопкой, он сдвигал бы кнопку под курсором.
 */
export function AccountLoginForm({ onSuccess }: AccountLoginFormProps) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const login = useAccountLogin();
  const emailId = useId();
  const passwordId = useId();
  const hintId = useId();
  const { t } = useTranslation('login');

  const failed = login.error !== null && login.error !== undefined;
  const ready = email.trim() !== '' && password !== '';

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!ready) return;
    login.mutate({ email, password }, { onSuccess });
  }

  /*
   * Отказы входа объясняются словами экрана входа, а не общим словарём ошибок: по коду
   * `unauthorized` словарь говорит о токене, а здесь не подошли почта или пароль —
   * различает это `details.reason`. Неверная почта и неверный пароль неразличимы
   * намеренно (иначе ответ выдавал бы, какие адреса заведены); отключённую учётную
   * запись бэкенд называет только после верного пароля.
   *
   * Окно попыток называет секунды из `details.retry_after`, а `details.scope` — чьё окно
   * кончилось (`TRK-113#10`). Тип `details` — `Record<string, unknown>` из
   * сгенерированного контракта: перечисления у `scope` там нет, поэтому незнакомое
   * значение читается как отсутствующее.
   */
  function refusal(error: Error): string {
    if (error instanceof ApiError && error.code === 'unauthorized') {
      return error.details.reason === 'account_disabled'
        ? t('accountDisabled')
        : t('credentialsWrong');
    }
    if (error instanceof ApiError && error.code === 'password_attempts_exceeded') {
      const seconds = Number(error.details.retry_after);
      if (Number.isFinite(seconds)) {
        if (error.details.scope === 'address') return t('throttledAddress', { seconds });
        if (error.details.scope === 'account') return t('throttledAccount', { seconds });
        if (error.details.scope === 'installation') {
          return t('throttledInstallation', { seconds });
        }
        return t('throttled', { seconds });
      }
    }
    return errorMessage(error);
  }

  return (
    <form className="flex flex-col gap-4" onSubmit={submit} noValidate>
      <div className="flex flex-col gap-2">
        <label className="font-semibold" htmlFor={emailId}>
          {t('emailLabel')}
        </label>
        <Input
          id={emailId}
          type="email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          autoComplete="username"
          spellCheck={false}
          aria-invalid={failed}
        />
      </div>

      <div className="flex flex-col gap-2">
        <label className="font-semibold" htmlFor={passwordId}>
          {t('passwordLabel')}
        </label>
        <Input
          id={passwordId}
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
        <Button type="submit" disabled={login.isPending || !ready}>
          {login.isPending ? t('submitting') : t('submit')}
        </Button>
      </div>

      {failed ? <Callout tone="danger">{refusal(login.error)}</Callout> : null}
    </form>
  );
}
