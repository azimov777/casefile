import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Activity,
  Ban,
  CalendarPlus,
  Hourglass,
  UserCheck,
  UserRound,
  type LucideIcon,
} from 'lucide-react';
import { Badge, RelativeTime } from '@/shared/ui';
import { cn } from '@/shared/lib';
import { isConnection, isRevoked, isSession, isThisComputer, type Token } from '../api/tokens';

/**
 * Один доступ установки: чей он, что открывает, кем и когда выпущен, когда им ходили
 * в последний раз и жив ли он ещё.
 *
 * Строкой-карточкой, а не строкой таблицы: значений шесть, и на узком экране таблица
 * из них либо уезжает вбок, либо схлопывает колонки до нечитаемого. Карточка
 * переносит своё содержимое сама и на любой ширине остаётся одним куском.
 *
 * Две строки и место действия справа (UI-131). Первая — что это за доступ: имя (у
 * подключения — клиент, у ключа этого компьютера — «этот компьютер»), вид, отметки. Вторая — сведения о нём, каждое со своим знаком: чей, кем выпущен, когда им
 * ходили; раньше они шли одной сплошной серой строкой, и глазу не за что было
 * зацепиться. Место действия стоит всегда, есть кнопка или нет: сетка в две колонки
 * не переносит кнопку на свою строку, и строки с отзывом и без него одной высоты.
 *
 * Ничего не вычисляет: «отозван» — это заполненный `revoked_at`, «общий» — пустой
 * `participant`, а «этот сеанс» приходит снаружи сравнением с `token.id` из
 * `GET /api/v1/bootstrap` (TRK/ui-api#8, «Токен сеанса»).
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
  const connection = isConnection(token);
  const session = isSession(token);
  const computer = isThisComputer(token);
  const grantedBy = author === null ? t('token.byTracker') : author;

  return (
    <article
      aria-label={t('token.label', { name: token.name })}
      data-token-kind={token.kind}
      data-revoked={revoked ? 'true' : undefined}
      className={cn(
        'grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-4 rounded-block border px-4 py-3',
        // Отозванный доступ остаётся историей. Отличается он заливкой и плашкой, а не
        // прозрачностью: та роняет контраст (`docs/notes/ui.md`).
        revoked ? 'border-line bg-sunken' : 'border-line bg-surface',
      )}
    >
      <div className="flex min-w-0 flex-col gap-1.5">
        <p className="flex flex-wrap items-center gap-x-2 gap-y-1">
          {/* Имя токена написал человек или установка: это данные, а не подпись. */}
          <span className="font-semibold wrap-anywhere text-text">
            {computer ? t('token.thisComputer') : token.name}
          </span>

          <Badge tone={connection ? 'progress' : 'neutral'}>{t(`token.kind.${token.kind}`)}</Badge>

          {current ? <Badge tone="progress">{t('token.thisSession')}</Badge> : null}
          {revoked ? <Badge tone="dropped">{t('token.revoked')}</Badge> : null}
        </p>

        <p className="flex flex-wrap items-center gap-x-4 gap-y-1 text-meta text-muted">
          {/* Чей доступ — первое, ради чего список открывают. Общий агентский токен
              не называет никого сам: каждый запрос с ним подписан меткой. */}
          <Fact icon={UserRound}>
            {shared ? (
              t('token.shared')
            ) : (
              <span className="font-mono text-text">{token.participant}</span>
            )}
          </Fact>

          {/* Срок сеанса входа; у подключения — срок его токена, который клиент продлевает
              сам. Ключ агента живёт до отзыва, и срока у него нет. */}
          {(session || connection) &&
          !revoked &&
          token.expires_at !== null &&
          token.expires_at !== undefined ? (
            <Fact icon={Hourglass}>
              {connection ? t('token.tokenExpires') : t('token.expiresAt')}{' '}
              <RelativeTime value={token.expires_at} />
            </Fact>
          ) : null}

          {revoked ? (
            <Fact icon={Ban}>
              {t('token.revokedAt')} <RelativeTime value={token.revoked_at} />
            </Fact>
          ) : null}

          {/* «Ни разу» — целая фраза, а не хвост к «последний раз ходили»: дописанное
              к началу, оно читается как оборванное предложение. */}
          <Fact icon={Activity}>
            {token.last_used_at === null || token.last_used_at === undefined ? (
              connection ? (
                t('token.neverCalled')
              ) : (
                t('token.neverUsed')
              )
            ) : (
              <>
                {connection ? t('token.lastCall') : t('token.lastUsed')}{' '}
                <RelativeTime value={token.last_used_at} />
              </>
            )}
          </Fact>

          {/* Кто выдал доступ: человек, который выпустил ключ или согласил подключение.
              У сеанса входа выдающего нет — это вход самого человека. */}
          {session ? null : (
            <Fact icon={UserCheck}>
              {connection
                ? t('token.connectedBy', { author: grantedBy })
                : t('token.grantedBy', { author: grantedBy })}
            </Fact>
          )}

          <Fact icon={CalendarPlus}>
            {session
              ? t('token.signedIn')
              : connection
                ? t('token.connectedAt')
                : t('token.issuedAt')}{' '}
            <RelativeTime value={token.created_at} />
          </Fact>
        </p>
      </div>

      <div className="flex min-h-(--ui-control-sm) items-center">{action}</div>
    </article>
  );
}

/** Одно сведение о доступе со своим знаком: знак — ориентир глазу, слова — диктору. */
function Fact({ icon: Icon, children }: { icon: LucideIcon; children: ReactNode }) {
  return (
    <span className="inline-flex min-w-0 items-center gap-1.5">
      <Icon className="size-(--ui-mark) shrink-0 text-faint" aria-hidden="true" />
      <span className="min-w-0">{children}</span>
    </span>
  );
}
