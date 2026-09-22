import { useId, useState, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { ApiError } from '@/shared/api';
import { errorMessage } from '@/shared/errors';
import { Button, Callout, Input } from '@/shared/ui';
import { useChangePassword } from '../model/use-change-password';

/**
 * Смена своего пароля: прежний, новый и новый ещё раз.
 *
 * Повтор нового сверяется здесь, до отправки: это не вычисление за бэкенд, а защита от
 * опечатки, которую бэкенд увидеть не может — он получил бы один пароль, и человек
 * заперся бы опечаткой. Длину и прочие требования проверяет бэкенд (`weak_password`).
 *
 * После удачи поля очищаются, а исход сказан словами: прочие сеансы закрыты, этот живёт.
 */
export function ChangePasswordForm({
  accountId,
  hasPassword,
}: {
  accountId: string;
  /** Есть ли пароль сейчас. Без него прежний не спрашивается: задаётся первый. */
  hasPassword: boolean;
}) {
  const change = useChangePassword();
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [repeat, setRepeat] = useState('');
  const [mismatch, setMismatch] = useState(false);
  const currentId = useId();
  const nextId = useId();
  const nextHintId = useId();
  const repeatId = useId();
  const { t } = useTranslation('account');

  const failed = change.error !== null && change.error !== undefined;
  const code = change.error instanceof ApiError ? change.error.code : null;
  const ready = (!hasPassword || current !== '') && next !== '' && repeat !== '';

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!ready) return;
    if (next !== repeat) {
      setMismatch(true);
      return;
    }
    setMismatch(false);
    change.mutate(
      { accountId, current: hasPassword ? current : null, next },
      {
        onSuccess: () => {
          setCurrent('');
          setNext('');
          setRepeat('');
        },
      },
    );
  }

  return (
    <form className="flex max-w-(--ui-text-max) flex-col gap-4" onSubmit={submit} noValidate>
      {hasPassword ? (
        <div className="flex flex-col gap-1">
          <label className="text-meta text-muted" htmlFor={currentId}>
            {t('password.currentLabel')}
          </label>
          <Input
            id={currentId}
            type="password"
            value={current}
            onChange={(event) => setCurrent(event.target.value)}
            autoComplete="current-password"
            spellCheck={false}
            aria-invalid={code === 'current_password_mismatch'}
          />
        </div>
      ) : null}

      <div className="flex flex-col gap-1">
        <label className="text-meta text-muted" htmlFor={nextId}>
          {t('password.newLabel')}
        </label>
        <Input
          id={nextId}
          type="password"
          value={next}
          onChange={(event) => setNext(event.target.value)}
          autoComplete="new-password"
          spellCheck={false}
          aria-invalid={code === 'weak_password'}
          aria-describedby={nextHintId}
        />
        <span className="text-meta text-muted" id={nextHintId}>
          {t('password.newHint')}
        </span>
      </div>

      <div className="flex flex-col gap-1">
        <label className="text-meta text-muted" htmlFor={repeatId}>
          {t('password.repeatLabel')}
        </label>
        <Input
          id={repeatId}
          type="password"
          value={repeat}
          onChange={(event) => setRepeat(event.target.value)}
          autoComplete="new-password"
          spellCheck={false}
          aria-invalid={mismatch}
        />
      </div>

      <div>
        <Button type="submit" disabled={change.isPending || !ready}>
          {change.isPending ? t('password.pending') : t('password.submit')}
        </Button>
      </div>

      {/* Исход — после кнопки, как на входе: появившись выше, он сдвигал бы кнопку. */}
      {mismatch ? <Callout tone="danger">{t('password.mismatch')}</Callout> : null}
      {failed ? <Callout tone="danger">{errorMessage(change.error)}</Callout> : null}
      {/* Область объявления стоит всегда: живая область, появившаяся вместе с текстом,
          программой чтения с экрана не объявляется. */}
      <div role="status">
        {change.isSuccess ? <Callout>{t('password.changed')}</Callout> : null}
      </div>
    </form>
  );
}
