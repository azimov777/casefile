import { useId, useState } from 'react';
import { useInfiniteQuery, useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { bootstrapQueryOptions } from '@/entities/session';
import { TokenItem, isRevoked, tokensQueryOptions, type Token } from '@/entities/token';
import { ConnectionSnippets, installationQueryOptions } from '@/features/connect-agent';
import {
  AgentDialog,
  IssueDialog,
  RevokeDialog,
  SecretDialog,
  type IssuedToken,
} from '@/features/manage-access';
import { Button, Callout, QueryState } from '@/shared/ui';

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
 * Экран «Доступы»: все токены установки, заведение агента, выпуск и отзыв.
 *
 * Список виден любым ключом — чтение токенов открыто набору `task` тоже. Запись
 * открыта, когда ключ сеанса набора `main` (`GET /api/v1/bootstrap` → `token.scope`),
 * и решает это набор, а не отказ: действия, которые ответили бы `403`, не
 * показываются доступными, и запросов записи с ключом `task` экран не делает вовсе.
 * Ввода ключа здесь нет и не будет — решение `UI-104#7`.
 */
export function AccessPage() {
  const bootstrap = useQuery(bootstrapQueryOptions());
  const tokens = useInfiniteQuery(tokensQueryOptions());
  const [flow, setFlow] = useState<Flow>({ kind: 'none' });
  const { t } = useTranslation('access');
  const { t: brick } = useTranslation('ui');

  const session = bootstrap.data?.token ?? null;
  const canWrite = session?.scope === 'main';
  const items = tokens.data?.pages.flatMap((page) => page.items) ?? [];

  /*
   * Адрес MCP нужен только окну секрета — но спрашивается он раньше, пока человек
   * заполняет форму выпуска: иначе окно с секретом открывалось бы состоянием
   * загрузки. Ответ держится всю жизнь вкладки (`installationQueryOptions`), поэтому
   * второго запроса не будет.
   */
  const needsAddress = flow.kind === 'issue' || flow.kind === 'secret';
  const installation = useQuery({ ...installationQueryOptions(), enabled: needsAddress });

  const closedId = useId();
  const actionsId = useId();
  const listId = useId();

  return (
    <main className="flex max-w-(--ui-page-max) flex-col gap-6">
      <div>
        {/* Название раздела одно на панель и на заголовок экрана. */}
        <h1 className="text-title">{brick('app.access')}</h1>
        <p className="mt-1 max-w-(--ui-text-max) text-meta text-muted">{t('intro')}</p>
      </div>

      <section aria-labelledby={actionsId} className="flex min-w-0 flex-col gap-3">
        <h2 id={actionsId} className="text-screen">
          {t('actions.title')}
        </h2>
        <p className="max-w-(--ui-text-max) text-body">{t('actions.intro')}</p>

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

        {/*
         * Почему запись закрыта — сказано там же, где стоят запрещённые кнопки, и они
         * же на это объяснение ссылаются: запрет без причины читается как поломка.
         * Пока набор ключа неизвестен (первый кадр ещё не пришёл), не говорится
         * ничего: «запись закрыта» о неизвестном — это выдумка, а не состояние.
         */}
        {session === null || canWrite ? null : (
          <Callout id={closedId}>{t('closed.text', { scope: session.scope })}</Callout>
        )}
        <QueryState query={bootstrap} loading={t('closed.loading')} compact />
      </section>

      <section aria-labelledby={listId} className="flex min-w-0 flex-col gap-3">
        <h2 id={listId} className="text-screen">
          {t('tokens.title')}
        </h2>
        <p className="max-w-(--ui-text-max) text-meta text-muted">{t('tokens.intro')}</p>

        <QueryState
          query={tokens}
          loading={t('tokens.loading')}
          empty={items.length === 0 ? t('tokens.empty') : undefined}
        />

        <ul className="flex list-none flex-col gap-2 p-0">
          {items.map((token) => (
            <li key={token.id}>
              <TokenItem
                token={token}
                current={session !== null && token.id === session.id}
                action={
                  canWrite && !isRevoked(token) ? (
                    <Button
                      tone="quiet"
                      className="px-2 py-1 text-meta"
                      onClick={() => setFlow({ kind: 'revoke', token })}
                    >
                      {t('revoke.action')}
                    </Button>
                  ) : undefined
                }
              />
            </li>
          ))}
        </ul>

        {tokens.hasNextPage ? (
          <div>
            <Button
              tone="quiet"
              onClick={() => void tokens.fetchNextPage()}
              disabled={tokens.isFetchingNextPage}
            >
              {tokens.isFetchingNextPage ? t('tokens.loadingMore') : t('tokens.more')}
            </Button>
          </div>
        ) : null}
      </section>

      {flow.kind === 'agent' ? (
        <AgentDialog
          onClose={() => setFlow({ kind: 'none' })}
          onIssueFor={(participant) => setFlow({ kind: 'issue', participant })}
        />
      ) : null}

      {flow.kind === 'issue' ? (
        <IssueDialog
          participant={flow.participant}
          onClose={() => setFlow({ kind: 'none' })}
          onIssued={(issued) => setFlow({ kind: 'secret', issued })}
        />
      ) : null}

      {flow.kind === 'secret' ? (
        <SecretDialog issued={flow.issued} onClose={() => setFlow({ kind: 'none' })}>
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
