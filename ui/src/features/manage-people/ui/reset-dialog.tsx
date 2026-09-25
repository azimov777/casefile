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
 * Кнопка «Сбросить пароль» у карточки учётной записи и окно сброса: новый пароль —
 * сгенерированный или вписанный.
 *
 * Роль `alertdialog`: сброс гасит все сеансы человека, и вошедший со старым паролем
 * выйдет на следующем же запросе — об этом спрашивают до, а не после. Сгенерированный
 * пароль уходит вызывающему (`onReset`) и показывается один раз.
 *
 * Своя кнопка и своё состояние открытия — на карточку (пропс `trigger`, `UI-175`), а не
 * одно окно на весь список с состоянием на странице: иначе Radix закрывал бы окно, не
 * зная, в какую из многих карточек вернуть фокус (`UI-175#11`, `UI-178`).
 */
export function ResetDialog({
  account,
  onReset,
}: {
  account: Account;
  onReset: (answer: AccountWithPassword) => void;
}) {
  const [open, setOpen] = useState(false);
  const { t } = useTranslation('people');

  return (
    <Dialog
      alert
      open={open}
      onOpenChange={setOpen}
      title={t('reset.title', { email: account.email })}
      description={t('reset.intro')}
      closeLabel={t('close')}
      trigger={
        <Button tone="quiet" className="px-2 py-1 text-meta">
          {t('reset.action')}
        </Button>
      }
    >
      <ResetForm
        account={account}
        onClose={() => setOpen(false)}
        onReset={(answer) => {
          setOpen(false);
          onReset(answer);
        }}
      />
    </Dialog>
  );
}

/** Форма сброса. Живёт в `children` окна и рождается заново на каждый заход. */
function ResetForm({
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
  );
}
