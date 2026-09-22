import { useState, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import type { Account } from '@/entities/account';
import { ApiError } from '@/shared/api';
import { errorMessage } from '@/shared/errors';
import { Button, Callout, Dialog } from '@/shared/ui';
import type { AccountWithPassword } from '../api/people';
import { useResetPassword } from '../model/use-people-actions';
import { PasswordChoice, type PasswordMode } from './password-choice';

/**
 * Сброс пароля товарищу: новый пароль — сгенерированный или вписанный.
 *
 * Роль `alertdialog`: сброс гасит все сеансы человека, и вошедший со старым паролем
 * выйдет на следующем же запросе — об этом спрашивают до, а не после. Сгенерированный
 * пароль уходит вызывающему (`onReset`) и показывается один раз.
 */
export function ResetDialog({
  account,
  onClose,
  onReset,
}: {
  account: Account;
  onClose: () => void;
  onReset: (answer: AccountWithPassword) => void;
}) {
  const reset = useResetPassword();
  const [mode, setMode] = useState<PasswordMode>('generate');
  const [password, setPassword] = useState('');
  const [empty, setEmpty] = useState(false);
  const { t } = useTranslation('people');

  const failed = reset.error !== null && reset.error !== undefined;
  const weak = reset.error instanceof ApiError && reset.error.code === 'weak_password';

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const missing = mode === 'type' && password === '';
    setEmpty(missing);
    if (missing) return;

    const answer = await reset.submit({
      accountId: account.id,
      password: mode === 'type' ? password : null,
    });
    if (answer !== null) onReset(answer);
  }

  return (
    <Dialog
      alert
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={t('reset.title', { email: account.email })}
      description={t('reset.intro')}
      closeLabel={t('close')}
    >
      <form className="flex flex-col gap-4" onSubmit={(event) => void submit(event)} noValidate>
        <PasswordChoice
          mode={mode}
          onModeChange={(next) => {
            setMode(next);
            setEmpty(false);
          }}
          password={password}
          onPasswordChange={setPassword}
          invalid={empty || weak}
        />
        {empty ? (
          <span className="text-meta text-danger" role="alert">
            {t('password.empty')}
          </span>
        ) : null}

        <div className="flex flex-wrap gap-2">
          <Button type="submit" disabled={reset.pending}>
            {reset.pending ? t('reset.pending') : t('reset.confirm')}
          </Button>
          <Button tone="quiet" onClick={onClose}>
            {t('cancel')}
          </Button>
        </div>

        {failed ? <Callout tone="danger">{errorMessage(reset.error)}</Callout> : null}
      </form>
    </Dialog>
  );
}
