import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Badge, RelativeTime } from '@/shared/ui';
import { cn } from '@/shared/lib';
import { isDisabled, type Account } from '../api/accounts';

/**
 * Одна учётная запись: почта входа, имя-подпись, администратор ли, отключена ли, кем и
 * когда заведена.
 *
 * Карточкой, а не строкой таблицы, — по той же причине, что строка доступа
 * (`entities/token`): на узком экране таблица либо уезжает вбок, либо схлопывает
 * колонки, а карточка переносит своё содержимое сама.
 *
 * Ничего не вычисляет: «отключена» — это заполненный `disabled_at`, «вы» приходит
 * снаружи сравнением с `account.id` из `GET /api/v1/bootstrap`.
 */
export function AccountItem({
  account,
  current = false,
  actions,
}: {
  account: Account;
  /** Это учётная запись того, кто смотрит. */
  current?: boolean;
  /** Что с учётной записью можно сделать. Кнопки рисует тот, кому это позволено. */
  actions?: ReactNode;
}) {
  const { t } = useTranslation('ui');
  const disabled = isDisabled(account);
  const author = account.created_by.signature ?? null;

  return (
    <article
      aria-label={t('account.label', { email: account.email })}
      data-disabled={disabled ? 'true' : undefined}
      className={cn(
        'flex flex-wrap items-start gap-x-4 gap-y-2 rounded-control border border-line p-3',
        // Отключённая учётная запись остаётся в списке: отличается заливкой и плашкой, а
        // не прозрачностью — та роняет контраст (`docs/notes/ui.md`).
        disabled ? 'bg-sunken' : 'bg-surface',
      )}
    >
      <div className="flex min-w-0 flex-col gap-1">
        <p className="flex flex-wrap items-center gap-2">
          {/* Почту вписал администратор: это данные, а не подпись; длинную переносим. */}
          <span className="font-medium wrap-anywhere text-text">{account.email}</span>
          {account.is_admin ? <Badge tone="attention">{t('account.admin')}</Badge> : null}
          {current ? <Badge tone="progress">{t('account.you')}</Badge> : null}
          {disabled ? <Badge tone="dropped">{t('account.disabled')}</Badge> : null}
        </p>

        <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-meta text-muted">
          <span>
            {t('account.signs')} <span className="font-mono text-text">{account.participant}</span>
          </span>
          <span>
            {author === null ? t('account.createdByTracker') : t('account.createdBy', { author })}{' '}
            <RelativeTime value={account.created_at} />
          </span>
          {account.has_password ? null : (
            <span className="text-faint">{t('account.noPassword')}</span>
          )}
          {disabled ? (
            <span>
              {t('account.disabledAt')} <RelativeTime value={account.disabled_at} />
            </span>
          ) : null}
        </p>
      </div>

      {actions === undefined ? null : <div className="ml-auto flex flex-wrap gap-2">{actions}</div>}
    </article>
  );
}
