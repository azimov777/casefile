import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Badge, RelativeTime } from '@/shared/ui';
import { cn } from '@/shared/lib';
import { isRevoked, type Token } from '../api/tokens';

/**
 * Один доступ установки: чей он, что открывает, кем и когда выпущен, когда им ходили
 * в последний раз и жив ли он ещё.
 *
 * Строкой-карточкой, а не строкой таблицы: значений шесть, и на узком экране таблица
 * из них либо уезжает вбок, либо схлопывает колонки до нечитаемого. Карточка
 * переносит своё содержимое сама и на любой ширине остаётся одним куском.
 *
 * Ничего не вычисляет: «отозван» — это заполненный `revoked_at`, «общий» — пустой
 * `participant`, а «этот сеанс» приходит снаружи сравнением с `token.id` из
 * `GET /api/v1/bootstrap` (`docs/FRONTEND.md`, «Токен сеанса»).
 */
export function TokenItem({
  token,
  current = false,
  action,
}: {
  token: Token;
  /** Этим ключом сделан запрос, которым нарисован экран. */
  current?: boolean;
  /** Что с доступом можно сделать: кнопка отзыва. Её рисует тот, кому это позволено. */
  action?: ReactNode;
}) {
  const { t } = useTranslation('ui');
  const revoked = isRevoked(token);
  const author = token.created_by.signature ?? null;
  const shared = token.participant === null || token.participant === undefined;

  return (
    <article
      aria-label={t('token.label', { name: token.name })}
      data-token-scope={token.scope}
      data-revoked={revoked ? 'true' : undefined}
      className={cn(
        'flex flex-wrap items-start gap-x-4 gap-y-2 rounded-control border border-line p-3',
        // Отозванный доступ остаётся в списке историей. Отличается он заливкой и
        // плашкой, а не прозрачностью: та роняет контраст (`docs/notes/ui.md`).
        revoked ? 'bg-sunken' : 'bg-surface',
      )}
    >
      <div className="flex min-w-0 flex-col gap-1">
        <p className="flex flex-wrap items-center gap-2">
          {/* Имя токена написал человек или установка: это данные, а не подпись. */}
          <span className="font-medium wrap-anywhere text-text">{token.name}</span>

          <Badge
            mono
            kind={t('token.scopeKind')}
            tone={token.scope === 'main' ? 'attention' : 'neutral'}
            title={t(token.scope === 'main' ? 'token.scopeMain' : 'token.scopeTask')}
          >
            {token.scope}
          </Badge>

          {current ? <Badge tone="progress">{t('token.thisSession')}</Badge> : null}
          {revoked ? <Badge tone="dropped">{t('token.revoked')}</Badge> : null}
        </p>

        <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-meta text-muted">
          {/* Чей доступ — первое, ради чего список открывают. Общий агентский токен
              не называет никого сам: каждый запрос с ним подписан меткой. */}
          {shared ? (
            <span>{t('token.shared')}</span>
          ) : (
            <span className="font-mono text-text">{token.participant}</span>
          )}

          <span>
            {author === null ? t('token.issuedByTracker') : t('token.issuedBy', { author })}{' '}
            <RelativeTime value={token.created_at} />
          </span>

          <span>
            {t('token.lastUsed')}{' '}
            {token.last_used_at === null || token.last_used_at === undefined ? (
              <span className="text-faint">{t('token.neverUsed')}</span>
            ) : (
              <RelativeTime value={token.last_used_at} />
            )}
          </span>

          {revoked ? (
            <span>
              {t('token.revokedAt')} <RelativeTime value={token.revoked_at} />
            </span>
          ) : null}
        </p>
      </div>

      {action === undefined ? null : <div className="ml-auto">{action}</div>}
    </article>
  );
}
