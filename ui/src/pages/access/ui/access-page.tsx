import { useEffect, useId, useState, type ReactNode } from 'react';
import { useInfiniteQuery, useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { useSearchParams } from 'react-router';
import { ChevronRight } from 'lucide-react';
import { bootstrapQueryOptions } from '@/entities/session';
import {
  TokenItem,
  belongsTo,
  isLive,
  isRevoked,
  isSession,
  tokensQueryOptions,
  type Token,
} from '@/entities/token';
import {
  CLIENT_PARAM,
  ConnectionSnippets,
  installationQueryOptions,
} from '@/features/connect-agent';
import {
  AgentDialog,
  IssueDialog,
  RevokeDialog,
  SecretDialog,
  type IssuedToken,
} from '@/features/manage-access';
import { cn, useExitHold } from '@/shared/lib';
import {
  Badge,
  Button,
  Callout,
  QueryState,
  Reveal,
  SegmentedNav,
  SegmentedNavLink,
} from '@/shared/ui';

/**
 * Параметр адреса вида списка у администратора: `?tokens=mine` — только свои, без
 * параметра — все токены установки. Вид живёт в адресе (`docs/CONVENTIONS.md`,
 * «Состояние»), а у умолчания параметра нет: у одного вида не бывает двух адресов.
 */
const TOKENS_PARAM = 'tokens';
const MINE = 'mine';

/**
 * Что человек делает на экране прямо сейчас. Одно окно за раз: заведение участника,
 * выпуск, показ секрета и подтверждение отзыва — шаги одной дороги, а не соседи.
 *
 * Секрет живёт здесь, в состоянии экрана, и нигде больше: ни в адресе, ни в
 * хранилищах браузера, ни в кэше запросов (`UI-106#18`). Закрытие окна стирает его.
 */
type Flow =
  | { kind: 'none' }
  | { kind: 'agent' }
  | { kind: 'issue'; participant: string | null }
  | { kind: 'secret'; issued: IssuedToken }
  | { kind: 'revoke'; token: Token };

/**
 * Экран «Доступы»: ключи агентов и сеансы входа, заведение агента, выпуск и отзыв.
 *
 * Чьи токены на экране, решает бэкенд (TRK-114#12): человеку без флага администратора —
 * свои (говорящие от его имени и выпущенные им), администратору — все токены установки,
 * а дорожка «Все / Мои» сужает до своих и его (`mine=true`). Экран этого не вычисляет —
 * он только называет, что показано.
 *
 * Три части. Действующие ключи — сверху и на виду; сеансы входа по почте (`expires_at`
 * заполнен) — своим разделом, только живые: это не доступ агента, а след каждого входа,
 * и среди ключей агентов они заслоняли бы то, ради чего экран открывают; отозванные
 * ключи — свёрнутой историей (UI-131). Закончившиеся сеансы не показываются вовсе.
 * Колонка та же, что у «Подключить агента»: `--ui-column-max` по центру области содержимого.
 *
 * Чтобы «действующие» были полными, список дочитывается до конца сам: действующий ключ,
 * выпущенный давно, мог стоять на второй странице выдачи, и кнопка «Показать ещё» под
 * историей его бы прятала. Доступов на установке — десятки, а не тысячи.
 *
 * Право решает первый кадр (`GET /api/v1/bootstrap`), а не отказ: действия, которые
 * ответили бы `403`, не показываются доступными, и запросов записи впустую экран не
 * делает. Выпуск и заведение агента — ключу набора `main` за человеком с учётной
 * записью (`account_required`); отзыв — своей строки всегда, чужой — только
 * администратору (`not_own_token`). Ввода ключа здесь нет и не будет — решение `UI-104#7`.
 */
export function AccessPage() {
  const bootstrap = useQuery(bootstrapQueryOptions());
  const [searchParams, setSearchParams] = useSearchParams();
  // Параметр шлётся как есть и до первого кадра: не администратору он ничего не меняет,
  // а администратор не получит сперва чужой вид, а потом свой.
  const mine = searchParams.get(TOKENS_PARAM) === MINE;
  const tokens = useInfiniteQuery(tokensQueryOptions({ mine }));
  const [flow, setFlow] = useState<Flow>({ kind: 'none' });
  const [historyOpen, setHistoryOpen] = useState(false);
  const history = useExitHold(historyOpen);
  const { t } = useTranslation('access');
  const { t: brick } = useTranslation('ui');

  const session = bootstrap.data?.token ?? null;
  const me = bootstrap.data?.participant?.name ?? null;
  const account = bootstrap.data?.account ?? null;
  const admin = account?.is_admin === true;
  /** Видит ли экран все токены установки, а не только свои. */
  const everyone = admin && !mine;
  const canRevoke = session?.scope === 'main';
  const canWrite = canRevoke && account !== null;

  const items = tokens.data?.pages.flatMap((page) => page.items) ?? [];
  const keys = items.filter((token) => !isSession(token));
  const active = keys.filter((token) => !isRevoked(token));
  const revoked = keys.filter(isRevoked);
  const sessions = items.filter((token) => isSession(token) && isLive(token));
  const complete = tokens.isSuccess && !tokens.hasNextPage;

  const { hasNextPage, isFetchingNextPage, isError, fetchNextPage } = tokens;
  useEffect(() => {
    if (hasNextPage && !isFetchingNextPage && !isError) void fetchNextPage();
  }, [hasNextPage, isFetchingNextPage, isError, fetchNextPage]);

  /*
   * Адрес MCP нужен только окну секрета — но спрашивается он раньше, пока человек
   * заполняет форму выпуска: иначе окно с секретом открывалось бы состоянием
   * загрузки. Ответ держится всю жизнь вкладки (`installationQueryOptions`), поэтому
   * второго запроса не будет.
   */
  const needsAddress = flow.kind === 'issue' || flow.kind === 'secret';
  const installation = useQuery({ ...installationQueryOptions(), enabled: needsAddress });

  /** Закрыть окно секрета: выбранный в нём клиент — вид окна, а не экрана, и уходит с ним. */
  function closeSecret() {
    setFlow({ kind: 'none' });
    if (searchParams.has(CLIENT_PARAM)) {
      const updated = new URLSearchParams(searchParams);
      updated.delete(CLIENT_PARAM);
      setSearchParams(updated, { replace: true });
    }
  }

  const closedId = useId();
  const activeId = useId();
  const sessionsId = useId();
  const historyId = useId();

  /** Вид списка администратора в адресе: прочие параметры остаются как были. */
  function viewSearch(onlyMine: boolean): string {
    const updated = new URLSearchParams(searchParams);
    if (onlyMine) updated.set(TOKENS_PARAM, MINE);
    else updated.delete(TOKENS_PARAM);
    const search = updated.toString();
    return search === '' ? '' : `?${search}`;
  }

  function revokeAction(token: Token) {
    return canRevoke && !isRevoked(token) && (admin || belongsTo(token, me)) ? (
      <Button tone="quiet" size="sm" onClick={() => setFlow({ kind: 'revoke', token })}>
        {t('revoke.action')}
      </Button>
    ) : undefined;
  }

  return (
    <main className="mx-auto flex max-w-(--ui-column-max) min-w-0 flex-col gap-8">
      <div className="flex flex-col gap-1">
        {/* Название раздела одно на панель и на заголовок экрана. */}
        <h1 className="text-title">{brick('app.access')}</h1>
        <p className="text-body text-muted">{everyone ? t('intro') : t('introMine')}</p>
      </div>

      {/* Дорожка — только администратору: остальным бэкенд отдаёт свои, и второго вида
          у них нет. */}
      {admin ? (
        <SegmentedNav label={t('view.label')} className="self-start">
          <SegmentedNavLink
            to={{ search: viewSearch(false) }}
            replace
            preventScrollReset
            current={everyone ? 'true' : false}
          >
            {t('view.all')}
          </SegmentedNavLink>
          <SegmentedNavLink
            to={{ search: viewSearch(true) }}
            replace
            preventScrollReset
            current={everyone ? false : 'true'}
          >
            {t('view.mine')}
          </SegmentedNavLink>
        </SegmentedNav>
      ) : null}

      <section aria-labelledby={activeId} className="flex min-w-0 flex-col gap-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 id={activeId} className="flex items-center gap-2 text-screen">
            {t('tokens.active')}
            {/* Счётчик склоняется для диктора, а глазу — одно число, как у входящей. */}
            {complete ? (
              <Badge>
                <span className="sr-only">{t('tokens.count', { count: active.length })}</span>
                <span aria-hidden="true">{active.length}</span>
              </Badge>
            ) : null}
          </h2>

          <div className="flex flex-wrap gap-2">
            <Button
              disabled={!canWrite}
              aria-describedby={canWrite ? undefined : closedId}
              onClick={() => setFlow({ kind: 'agent' })}
            >
              {t('actions.newAgent')}
            </Button>
            <Button
              tone="quiet"
              disabled={!canWrite}
              aria-describedby={canWrite ? undefined : closedId}
              onClick={() => setFlow({ kind: 'issue', participant: null })}
            >
              {t('actions.issue')}
            </Button>
          </div>
        </div>

        <p className="text-meta text-muted">{t('actions.intro')}</p>

        {/*
         * Почему запись закрыта — сказано там же, где стоят запрещённые кнопки, и они
         * же на это объяснение ссылаются: запрет без причины читается как поломка.
         * Пока набор ключа неизвестен (первый кадр ещё не пришёл), не говорится
         * ничего: «запись закрыта» о неизвестном — это выдумка, а не состояние.
         */}
        {session === null || canWrite ? null : (
          <Callout id={closedId}>
            {canRevoke ? t('closed.noAccount') : t('closed.text', { scope: session.scope })}
          </Callout>
        )}
        <QueryState query={bootstrap} loading={t('closed.loading')} compact />

        <QueryState
          query={tokens}
          loading={t('tokens.loading')}
          empty={
            complete && keys.length === 0
              ? everyone
                ? t('tokens.empty')
                : t('tokens.emptyMine')
              : undefined
          }
        />

        {complete && keys.length > 0 && active.length === 0 ? (
          <p className="text-body text-muted">{t('tokens.noActive')}</p>
        ) : null}

        <TokenList tokens={active} session={session?.id ?? null} action={revokeAction} />

        {hasNextPage ? <p className="text-meta text-muted">{t('tokens.loadingMore')}</p> : null}
      </section>

      {sessions.length === 0 ? null : (
        <section aria-labelledby={sessionsId} className="flex min-w-0 flex-col gap-3">
          <h2 id={sessionsId} className="flex items-center gap-2 text-screen">
            {t('sessions.title')}
            <Badge>
              <span className="sr-only">{t('sessions.count', { count: sessions.length })}</span>
              <span aria-hidden="true">{sessions.length}</span>
            </Badge>
          </h2>
          <p className="text-meta text-muted">{t('sessions.intro')}</p>
          <TokenList tokens={sessions} session={session?.id ?? null} action={revokeAction} />
        </section>
      )}

      {revoked.length === 0 ? null : (
        <section aria-labelledby={historyId} className="flex min-w-0 flex-col">
          {/* Кнопка раскрытия внутри заголовка: у раздела остаётся имя, а у кнопки —
              состояние `aria-expanded` (образец «disclosure» WAI-ARIA). */}
          <h2 id={historyId} className="text-screen">
            <Button
              tone="quiet"
              aria-expanded={historyOpen}
              aria-controls={`${historyId}-list`}
              onClick={() => setHistoryOpen(!historyOpen)}
            >
              <ChevronRight
                aria-hidden="true"
                className={cn(
                  'size-(--ui-mark) transition-transform duration-(--motion-fast) ease-fast',
                  historyOpen ? 'rotate-90' : '',
                )}
              />
              {t('tokens.history', { count: revoked.length })}
            </Button>
          </h2>

          {history.held ? (
            <Reveal hold={history}>
              <div id={`${historyId}-list`} className="flex flex-col gap-3 pt-3">
                <p className="text-meta text-muted">{t('tokens.historyIntro')}</p>
                <TokenList tokens={revoked} session={session?.id ?? null} />
              </div>
            </Reveal>
          ) : null}
        </section>
      )}

      {flow.kind === 'agent' ? (
        <AgentDialog
          onClose={() => setFlow({ kind: 'none' })}
          onIssueFor={(participant) => setFlow({ kind: 'issue', participant })}
        />
      ) : null}

      {flow.kind === 'issue' ? (
        <IssueDialog
          participant={flow.participant}
          me={me}
          admin={admin}
          onClose={() => setFlow({ kind: 'none' })}
          onIssued={(issued) => setFlow({ kind: 'secret', issued })}
        />
      ) : null}

      {flow.kind === 'secret' ? (
        <SecretDialog issued={flow.issued} onClose={closeSecret}>
          {/* Фрагменты подключения — тот же компонент, что и на экране «Подключить
              агента» (UI-105), только с настоящим секретом вместо подстановки. */}
          <QueryState query={installation} loading={t('secret.loadingAddress')} />
          {installation.data === undefined ? null : (
            <ConnectionSnippets
              mcpUrl={installation.data.mcp_url}
              token={flow.issued.secret}
              labelled={flow.issued.participant === null}
            />
          )}
        </SecretDialog>
      ) : null}

      {flow.kind === 'revoke' ? (
        <RevokeDialog
          token={flow.token}
          current={session !== null && flow.token.id === session.id}
          onClose={() => setFlow({ kind: 'none' })}
        />
      ) : null}
    </main>
  );
}

/** Список доступов карточками; действие у строки — от того, кому оно позволено. */
function TokenList({
  tokens,
  session,
  action,
}: {
  tokens: Token[];
  /** `id` ключа этого сеанса: его строка отмечена. */
  session: string | null;
  action?: (token: Token) => ReactNode;
}) {
  if (tokens.length === 0) return null;

  return (
    <ul className="m-0 flex list-none flex-col gap-2 p-0">
      {tokens.map((token) => (
        <li key={token.id}>
          <TokenItem token={token} current={token.id === session} action={action?.(token)} />
        </li>
      ))}
    </ul>
  );
}
