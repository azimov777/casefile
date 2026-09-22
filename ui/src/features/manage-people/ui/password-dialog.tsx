import { useTranslation } from 'react-i18next';
import { Button, Callout, CopyBlock, Dialog } from '@/shared/ui';

/**
 * Окно пароля, который только что сгенерировал трекер: единственный раз, когда его видно.
 *
 * Второго показа нет и быть не может — в базе лежит хеш, — и администратору сказано об
 * этом до того, как он закроет окно, а не после. Пароль приходит пропсом из состояния
 * экрана и больше нигде не живёт: ни в адресе, ни в хранилищах браузера, ни в кэше
 * запросов, ни в журнале. Закрытие окна снимает узел вместе с блоком копирования.
 */
export function PasswordDialog({
  email,
  password,
  reset,
  onClose,
}: {
  email: string;
  password: string;
  /** Пароль после сброса, а не при заведении: другой заголовок и другое последствие. */
  reset: boolean;
  onClose: () => void;
}) {
  const { t } = useTranslation('people');

  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={reset ? t('once.resetTitle', { email }) : t('once.createdTitle', { email })}
      description={t('once.intro')}
      closeLabel={t('close')}
    >
      {/* Предупреждение стоит над паролем: закрывший окно обязан узнать об этом до. */}
      <Callout tone="danger">{t('once.onlyOnce')}</Callout>

      <CopyBlock label={t('once.emailLabel')} caption={t('once.emailCaption')} text={email} />
      <CopyBlock
        label={t('once.passwordLabel')}
        caption={t('once.passwordCaption')}
        text={password}
      />

      <div>
        <Button onClick={onClose}>{t('once.done')}</Button>
      </div>
    </Dialog>
  );
}
