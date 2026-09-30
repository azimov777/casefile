import { useEffect, useId, useState, type ReactNode } from 'react';
import { useInfiniteQuery, useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { useSearchParams } from 'react-router';
import { ChevronRight } from 'lucide-react';
import { bootstrapQueryOptions } from '@/entities/session';
import {
  TokenItem,
  belongsTo,
  isConnection,
  isKey,
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
import { ExplanationPanel, HINT_KEYS } from '@/features/manage-onboarding';
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

/*
 * Заведение участника, выпуск и показ секрета — шаги одной дороги (окна модальны, и
 * Radix не даёт открыть второе поверх первого), но не общее состояние страницы: у
 * каждого окна своя кнопка-триггер (`UI-175`), а Radix держит её смонтированной
 * постоянно — иначе после `Esc` и «Закрыть» ему было бы некуда вернуть фокус
 * (`UI-175#11`, `UI-178`). Отзыв — окно на каждую строку (`RevokeDialog`), своё
 * состояние открытия внутри неё же.
 *
 * Секрет живёт здесь, в состоянии экрана, и нигде больше: ни в адресе, ни в
 * хранилищах браузера, ни в кэше запросов (`UI-106#18`). Закрытие окна стирает его.
 */

/**
 * Экран «Доступы»: подключения агентов, ключи агентов и сеансы входа, заведение агента,
 * выпуск ключа и отзыв (TRK-473, решение `TRK-469#25`).
 *
 * Чьи доступы на экране, решает бэкенд (TRK-114#12): человеку без флага администратора —
 * свои (говорящие от его имени и выданные им), администратору — все доступы установки,
 * а дорожка «Все / Мои» сужает до своих и его (`mine=true`). Экран этого не вычисляет —
 * он только называет, что показано.
 *
 * Список делится по `kind` строки: «Подключения» (`oauth`: агент вошёл сам, секрета
 * человек не видел), «Ключи агентов» (`key`: статический секрет, его выдал человек) и
 * «Сеансы входа» (`session`: вход самого человека; ключ `local-ui` — «этот компьютер»).
 * Снятые подключения и ключи — свёрнутой историей (UI-131). Закрытые и закончившиеся
 * сеансы не показываются вовсе. Колонка та же, что у «Подключить агента»: `--ui-column-max` по
 * центру области содержимого.
 *
 * Чтобы разделы были полными, список дочитывается до конца сам: доступ, выданный давно,
 * мог стоять на второй странице выдачи, и кнопка «Показать ещё» под историей его бы
 * прятала. Доступов на установке — десятки, а не тысячи.
 *
 * Право решает первый кадр (`GET /api/v1/bootstrap`), а не отказ: выпуск и заведение
 * агента — человеку с учётной записью (`account_required`); отзыв — своей строки всегда,
 * чужой — только администратору (`not_own_token`). Наборов токена больше нет (TRK-471),
 * и экран их не читает. Ввода ключа здесь нет и не будет — решение `UI-104#7`.
 */
export function AccessPage() {
  const bootstrap = useQuery(bootstrapQueryOptions());
  const [searchParams, setSearchParams] = useSearchParams();
  // Параметр шлётся как есть и до первого кадра: не администратору он ничего не меняет,
  // а администратор не получит сперва чужой вид, а потом свой.
  const mine = searchParams.get(TOKENS_PARAM) === MINE;
  const tokens = useInfiniteQuery(tokensQueryOptions({ mine }));
  const [agentOpen, setAgentOpen] = useState(false);
  const [issueOpen, setIssueOpen] = useState(false);
  /** Кому выпускаем: `null` — выбор в форме, имя — пришло из «Выпустить ему токен». */
  const [issueParticipant, setIssueParticipant] = useState<string | null>(null);
  const [issued, setIssued] = useState<IssuedToken | null>(null);
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
  const canWrite = account !== null;

  const items = tokens.data?.pages.flatMap((page) => page.items) ?? [];
  const connections = items.filter((token) => isConnection(token) && isLive(token));
  const keys = items.filter((token) => isKey(token) && isLive(token));
  const sessions = items.filter((token) => isSession(token) && isLive(token));
  // Снятые подключения и ключи — историей. Сеансы входа в неё не идут: выход и истёкший
  // срок — обычная жизнь входа, а не снятый доступ агента, и каждый выход засорял бы её.
  const revoked = items.filter((token) => isRevoked(token) && !isSession(token));
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
  const needsAddress = issueOpen || issued !== null;
  const installation = useQuery({ ...installationQueryOptions(), enabled: needsAddress });

  /** Закрыть окно секрета: выбранный в нём клиент — вид окна, а не экрана, и уходит с ним. */
  function closeSecret() {
    setIssued(null);
    if (searchParams.has(CLIENT_PARAM)) {
      const updated = new URLSearchParams(searchParams);
      updated.delete(CLIENT_PARAM);
      setSearchParams(updated, { replace: true });
    }
  }

  const closedId = useId();
  const connectionsId = useId();
  const keysId = useId();
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
    return !isRevoked(token) && (admin || belongsTo(token, me)) ? (
      <RevokeDialog token={token} current={session !== null && token.id === session.id} />
    ) : undefined;
  }

  return (
    <main className="mx-auto flex max-w-(--ui-column-max) min-w-0 flex-col gap-8">
      {/* Пояснение экрана — первым блоком (TRK-363). */}
      <ExplanationPanel hintKey={HINT_KEYS.access}>{t('explanation.body')}</ExplanationPanel>

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

      <QueryState query={tokens} loading={t('loading')} />

      <section aria-labelledby={connectionsId} className="flex min-w-0 flex-col gap-3">
        <SectionHead id={connectionsId} title={t('connections.title')} shown={complete}>
          <span className="sr-only">{t('connections.count', { count: connections.length })}</span>
          <span aria-hidden="true">{connections.length}</span>
        </SectionHead>
        <p className="text-meta text-muted">{t('connections.intro')}</p>

        {complete && connections.length === 0 ? (
          <p className="text-body text-muted">
            {everyone ? t('connections.empty') : t('connections.emptyMine')}
          </p>
        ) : null}
        <TokenList tokens={connections} session={session?.id ?? null} action={revokeAction} />
      </section>

      <section aria-labelledby={keysId} className="flex min-w-0 flex-col gap-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <SectionHead id={keysId} title={t('keys.title')} shown={complete}>
            <span className="sr-only">{t('keys.count', { count: keys.length })}</span>
            <span aria-hidden="true">{keys.length}</span>
          </SectionHead>

          <div className="flex flex-wrap gap-2">
            <AgentDialog
              open={agentOpen}
              onOpenChange={setAgentOpen}
              trigger={
                <Button disabled={!canWrite} aria-describedby={canWrite ? undefined : closedId}>
                  {t('actions.newAgent')}
                </Button>
              }
              onIssueFor={(participant) => {
                setIssueParticipant(participant);
                setIssueOpen(true);
              }}
            />
            <IssueDialog
              participant={issueParticipant}
              me={me}
              admin={admin}
              open={issueOpen}
              onOpenChange={setIssueOpen}
              trigger={
                <Button
                  tone="quiet"
                  disabled={!canWrite}
                  aria-describedby={canWrite ? undefined : closedId}
                  // Своя кнопка открывает выбором из формы: участник из «Выпустить ему
                  // ключ» не должен пережить закрытие и подставиться сюда молча.
                  onClick={() => setIssueParticipant(null)}
                >
                  {t('actions.issue')}
                </Button>
              }
              onIssued={(newlyIssued) => {
                setIssueOpen(false);
                setIssued(newlyIssued);
              }}
            />
          </div>
        </div>

        <p className="text-meta text-muted">{t('keys.intro')}</p>
        <p className="text-meta text-muted">{t('actions.intro')}</p>

        {/*
         * Почему выпуск закрыт — сказано там же, где стоят запрещённые кнопки, и они
         * же на это объяснение ссылаются: запрет без причины читается как поломка.
         * Пока первый кадр не пришёл, не говорится ничего: «выпуск закрыт» о неизвестном
         * — это выдумка, а не состояние.
         */}
        {session === null || canWrite ? null : (
          <Callout id={closedId}>{t('closed.noAccount')}</Callout>
        )}
        <QueryState query={bootstrap} loading={t('closed.loading')} compact />

        {complete && keys.length === 0 ? (
          <p className="text-body text-muted">{everyone ? t('keys.empty') : t('keys.emptyMine')}</p>
        ) : null}
        <TokenList tokens={keys} session={session?.id ?? null} action={revokeAction} />

        {hasNextPage ? <p className="text-meta text-muted">{t('loadingMore')}</p> : null}
      </section>

      {sessions.length === 0 ? null : (
        <section aria-labelledby={sessionsId} className="flex min-w-0 flex-col gap-3">
          <SectionHead id={sessionsId} title={t('sessions.title')} shown>
            <span className="sr-only">{t('sessions.count', { count: sessions.length })}</span>
            <span aria-hidden="true">{sessions.length}</span>
          </SectionHead>
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
              {t('history.count', { count: revoked.length })}
            </Button>
          </h2>

          {history.held ? (
            <Reveal hold={history}>
              <div id={`${historyId}-list`} className="flex flex-col gap-3 pt-3">
                <p className="text-meta text-muted">{t('history.intro')}</p>
                <TokenList tokens={revoked} session={session?.id ?? null} />
              </div>
            </Reveal>
          ) : null}
        </section>
      )}

      {/* Окно секрета — по-прежнему только по `issued`: открывает его не кнопка, а ход
          работы (успешный выпуск), и триггера у него нет (`UI-175#11`, тот же случай,
          что у пароля на экране «Люди»; фокус для таких окон — отдельное решение,
          вне этой задачи). */}
      {issued === null ? null : (
        <SecretDialog issued={issued} onClose={closeSecret}>
          {/* Фрагменты подключения — тот же компонент, что и на экране «Подключить
              агента» (UI-105), только с настоящим секретом вместо подстановки. */}
          <QueryState query={installation} loading={t('secret.loadingAddress')} />
          {installation.data === undefined ? null : (
            <ConnectionSnippets
              mcpUrl={installation.data.mcp_url}
              token={issued.secret}
              labelled={issued.participant === null}
            />
          )}
        </SecretDialog>
      )}
    </main>
  );
}

/** Заголовок раздела: название и счётчик (глазу — число, диктору — фраза, как у входящей). */
function SectionHead({
  id,
  title,
  shown,
  children,
}: {
  id: string;
  title: string;
  /** Показывать ли счётчик: пока список не дочитан, число было бы неполным. */
  shown: boolean;
  children: ReactNode;
}) {
  return (
    <h2 id={id} className="flex items-center gap-2 text-screen">
      {title}
      {shown ? <Badge>{children}</Badge> : null}
    </h2>
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
