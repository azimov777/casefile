import { useTranslation } from 'react-i18next';
import { isDisabled, type Account } from '@/entities/account';
import { errorMessage } from '@/shared/errors';
import { Button, Callout, Dialog } from '@/shared/ui';
import { useSetDisabled } from '../model/use-people-actions';

/**
 * Отключение учётной записи или её включение обратно.
 *
 * Отключение спрашивается окном `alertdialog`: оно закрывает вход и отзывает **все**
 * токены участника — и сеансы, и выпущенные его агентам, — а включение отозванного не
 * вернёт. Подписи человека в делах остаются: участник не удаляется никогда.
 * Включение обратимо и последствий не прячет, но идёт тем же окном — чтобы у обоих
 * действий было одно место, где сказан исход.
 */
export function DisableDialog({ account, onClose }: { account: Account; onClose: () => void }) {
  const toggle = useSetDisabled();
  const { t } = useTranslation('people');
  const enabling = isDisabled(account);
  const failed = toggle.error !== null && toggle.error !== undefined;

  return (
    <Dialog
      alert={!enabling}
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={
        enabling
          ? t('enable.title', { email: account.email })
          : t('disable.title', { email: account.email })
      }
      description={enabling ? t('enable.intro') : t('disable.intro')}
      closeLabel={t('close')}
    >
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
    </Dialog>
  );
}
