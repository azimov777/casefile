import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { isDisabled, type Account } from '@/entities/account';
import { errorMessage } from '@/shared/errors';
import { Button, Callout, Dialog } from '@/shared/ui';
import { useSetDisabled } from '../model/use-people-actions';

/**
 * Кнопка «Отключить»/«Включить» у карточки учётной записи и окно отключения или
 * включения обратно.
 *
 * Отключение спрашивается окном `alertdialog`: оно закрывает вход и отзывает **все**
 * токены участника — и сеансы, и выпущенные его агентам, — а включение отозванного не
 * вернёт. Подписи человека в делах остаются: участник не удаляется никогда.
 * Включение обратимо и последствий не прячет, но идёт тем же окном — чтобы у обоих
 * действий было одно место, где сказан исход.
 *
 * Своя кнопка и своё состояние открытия — на карточку (пропс `trigger`, `UI-175`), а не
 * одно окно на весь список с состоянием на странице: иначе Radix закрывал бы окно, не
 * зная, в какую из многих карточек вернуть фокус (`UI-175#11`, `UI-178`).
 */
export function DisableDialog({ account }: { account: Account }) {
  const [open, setOpen] = useState(false);
  const { t } = useTranslation('people');
  const enabling = isDisabled(account);

  return (
    <Dialog
      alert={!enabling}
      open={open}
      onOpenChange={setOpen}
      title={
        enabling
          ? t('enable.title', { email: account.email })
          : t('disable.title', { email: account.email })
      }
      description={enabling ? t('enable.intro') : t('disable.intro')}
      closeLabel={t('close')}
      trigger={
        <Button tone="quiet" className="px-2 py-1 text-meta">
          {enabling ? t('enable.action') : t('disable.action')}
        </Button>
      }
    >
      <DisableForm account={account} onClose={() => setOpen(false)} />
    </Dialog>
  );
}

/** Форма подтверждения. Живёт в `children` окна и рождается заново на каждый заход. */
function DisableForm({ account, onClose }: { account: Account; onClose: () => void }) {
  const toggle = useSetDisabled();
  const { t } = useTranslation('people');
  const enabling = isDisabled(account);
  const failed = toggle.error !== null && toggle.error !== undefined;

  return (
    <>
      <div className="flex flex-wrap gap-2">
        <Button
          disabled={toggle.isPending}
          onClick={() =>
            toggle.mutate({ accountId: account.id, disabled: !enabling }, { onSuccess: onClose })
          }
        >
          {toggle.isPending
            ? t('disable.pending')
            : enabling
              ? t('enable.confirm')
              : t('disable.confirm')}
        </Button>
        <Button tone="quiet" onClick={onClose}>
          {t('cancel')}
        </Button>
      </div>

      {failed ? <Callout tone="danger">{errorMessage(toggle.error)}</Callout> : null}
    </>
  );
}
