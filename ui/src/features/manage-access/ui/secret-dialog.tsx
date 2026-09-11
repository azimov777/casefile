import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Button, Callout, CopyBlock, Dialog } from '@/shared/ui';
import type { IssuedToken } from '../api/access';

/**
 * Окно только что выпущенного секрета: единственный раз, когда его видно.
 *
 * Второго показа нет и быть не может — в базе лежит хеш (`app/domain/tokens.py`), —
 * и человеку сказано об этом до того, как он закроет окно, а не после.
 *
 * Фрагменты подключения приходят детьми, а не собираются здесь: их собирает
 * `ConnectionSnippets` из `features/connect-agent` (UI-105), а срез `features` не
 * вправе импортировать соседний срез своего слоя — поэтому их подставляет страница.
 *
 * Закрытие уносит секрет из состояния экрана: узел снимается вместе со всем, что
 * знал, — и с блоками копирования, в которых секрет стоял текстом.
 */
export function SecretDialog({
  issued,
  onClose,
  children,
}: {
  issued: IssuedToken;
  onClose: () => void;
  /** Фрагменты подключения с подставленным секретом. */
  children: ReactNode;
}) {
  const { t } = useTranslation('access');
  const participant = issued.participant ?? null;

  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={t('secret.title', { name: issued.name })}
      description={t('secret.intro')}
      closeLabel={t('close')}
    >
      {/* Предупреждение стоит над секретом, а не под ним: человек, закрывший окно,
          обязан узнать об этом до, а не после. */}
      <Callout tone="danger">{t('secret.onlyOnce')}</Callout>

      <p className="max-w-(--ui-text-max) text-meta text-muted">
        {participant === null ? t('secret.forShared') : t('secret.forParticipant', { participant })}
      </p>

      <CopyBlock
        label={t('secret.tokenLabel')}
        caption={t('secret.tokenCaption')}
        text={issued.secret}
      />

      {children}

      <div>
        <Button onClick={onClose}>{t('secret.done')}</Button>
      </div>
    </Dialog>
  );
}
