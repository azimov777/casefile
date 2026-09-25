import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { Token } from '@/entities/token';
import { errorMessage } from '@/shared/errors';
import { Button, Callout, Dialog } from '@/shared/ui';
import { denialReason } from '../model/problem';
import { useRevokeToken } from '../model/use-access-actions';

/**
 * Кнопка «Отозвать» у строки доступа и подтверждение отзыва: действие необратимо, и
 * спрашивают о нём до, а не после.
 *
 * Отзыв ключа, которым работает сам интерфейс, не запрещён — запрет был бы вторым
 * поведением ровно там, где действие нужнее всего (утёкший ключ отзывают немедленно,
 * а не «после следующего подъёма»). Вместо запрета окно называет последствия:
 * сеанс оборвётся на следующем же запросе (`UI-106#18`).
 *
 * Роль `alertdialog`: окно спрашивает о необратимом, и программа чтения с экрана
 * обязана объявить его вопросом, а не просто окном.
 *
 * Своя кнопка и своё состояние открытия — на строку (пропс `trigger`, `UI-175`), а не
 * одно окно на весь список с состоянием на странице: иначе Radix закрывал бы окно, не
 * зная, в какую из многих строк вернуть фокус (`UI-175#11`, `UI-178`).
 */
export function RevokeDialog({
  token,
  current,
}: {
  token: Token;
  /** Это ключ текущего сеанса: его отзыв обрывает работу самого интерфейса. */
  current: boolean;
}) {
  const [open, setOpen] = useState(false);
  const { t } = useTranslation('access');

  return (
    <Dialog
      alert
      open={open}
      onOpenChange={setOpen}
      title={t('revoke.title', { name: token.name })}
      description={t('revoke.intro')}
      closeLabel={t('close')}
      trigger={
        <Button tone="quiet" size="sm">
          {t('revoke.action')}
        </Button>
      }
    >
      <RevokeForm token={token} current={current} onClose={() => setOpen(false)} />
    </Dialog>
  );
}

/** Форма подтверждения. Живёт в `children` окна и рождается заново на каждый заход. */
function RevokeForm({
  token,
  current,
  onClose,
}: {
  token: Token;
  current: boolean;
  onClose: () => void;
}) {
  const revoke = useRevokeToken();
  const { t } = useTranslation('access');
  const failed = revoke.error !== null && revoke.error !== undefined;
  const denied = denialReason(revoke.error);

  return (
    <>
      {current ? <Callout tone="danger">{t('revoke.ownKey')}</Callout> : null}

      <div className="flex flex-wrap gap-2">
        <Button
          disabled={revoke.isPending}
          onClick={() => revoke.mutate(token.id, { onSuccess: onClose })}
        >
          {revoke.isPending ? t('revoke.pending') : t('revoke.confirm')}
        </Button>
        <Button tone="quiet" onClick={onClose}>
          {t('cancel')}
        </Button>
      </div>

      {failed ? (
        <Callout tone="danger">
          {errorMessage(revoke.error)} {denied === null ? null : t(`denied.${denied}`)}
        </Callout>
      ) : null}
    </>
  );
}
