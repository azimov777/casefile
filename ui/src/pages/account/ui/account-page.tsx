import { useId } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { bootstrapQueryOptions } from '@/entities/session';
import { ChangePasswordForm } from '@/features/change-password';
import { Badge, QueryState } from '@/shared/ui';

/**
 * Экран «Моя учётная запись»: кто я на этой установке и смена своего пароля.
 *
 * Всё о себе берётся из первого кадра (`bootstrap.account`): отдельного запроса «кто я»
 * в контракте нет и не нужно. Экран есть только в режиме входа по учётным записям — на
 * своей машине пароля нет и менять нечего (страж маршрутов, `app/routes`).
 */
export function AccountPage() {
  const bootstrap = useQuery(bootstrapQueryOptions());
  const account = bootstrap.data?.account ?? null;
  const { t } = useTranslation('account');
  const { t: brick } = useTranslation('ui');
  const passwordId = useId();

  return (
    <main className="flex max-w-(--ui-page-max) flex-col gap-6">
      <div>
        <h1 className="text-title">{brick('app.account')}</h1>
        <p className="mt-1 max-w-(--ui-text-max) text-meta text-muted">{t('intro')}</p>
      </div>

      <QueryState query={bootstrap} loading={t('loading')} compact />

      {/* Ключ без учётной записи (введённый токен агента или человека без неё): менять
          здесь нечего, и сказано это словами, а не пустым экраном. */}
      {bootstrap.data !== undefined && account === null ? (
        <p className="max-w-(--ui-text-max) text-body">{t('none')}</p>
      ) : null}

      {account === null ? null : (
        <>
          <dl className="grid max-w-(--ui-text-max) grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-body">
            <dt className="text-muted">{t('email')}</dt>
            <dd className="wrap-anywhere">{account.email}</dd>
            <dt className="text-muted">{t('signs')}</dt>
            <dd className="font-mono">{account.participant}</dd>
            <dt className="text-muted">{t('role')}</dt>
            <dd>
              {account.is_admin ? (
                <Badge tone="attention">{brick('account.admin')}</Badge>
              ) : (
                t('member')
              )}
            </dd>
          </dl>

          <section aria-labelledby={passwordId} className="flex min-w-0 flex-col gap-3">
            <h2 id={passwordId} className="text-screen">
              {t('password.title')}
            </h2>
            <p className="max-w-(--ui-text-max) text-meta text-muted">{t('password.intro')}</p>
            <ChangePasswordForm accountId={account.id} hasPassword={account.has_password} />
          </section>
        </>
      )}
    </main>
  );
}
