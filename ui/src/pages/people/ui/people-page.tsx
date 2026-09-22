import { useId, useState } from 'react';
import { useInfiniteQuery, useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { AccountItem, accountsQueryOptions, isDisabled, type Account } from '@/entities/account';
import { bootstrapQueryOptions } from '@/entities/session';
import { CreateDialog, DisableDialog, PasswordDialog, ResetDialog } from '@/features/manage-people';
import { Button, Callout, QueryState } from '@/shared/ui';

/**
 * Что администратор делает на экране прямо сейчас. Одно окно за раз.
 *
 * Пароль из ответа живёт здесь, в состоянии экрана, и нигде больше: ни в адресе, ни в
 * хранилищах браузера, ни в кэше запросов. Закрытие окна стирает его.
 */
type Flow =
  | { kind: 'none' }
  | { kind: 'create' }
  | { kind: 'password'; email: string; password: string; reset: boolean }
  | { kind: 'reset'; account: Account }
  | { kind: 'toggle'; account: Account };

/**
 * Экран «Люди»: учётные записи установки и управление ими — завести товарища, отключить,
 * включить, сбросить пароль (`TRK-113`).
 *
 * Только администратору, и решает это флаг из первого кадра (`bootstrap.account.is_admin`),
 * а не отказ `403`: неадминистратор видит объяснение, и запроса `GET /api/v1/accounts`
 * экран не делает вовсе. На своей машине экрана нет совсем — его прячет страж маршрутов
 * режима входа (`app/routes`).
 *
 * Свою учётную запись администратор здесь не отключает и не сбрасывает: первое оборвало
 * бы его же работу, второе погасило бы его сеанс; свой пароль меняют на экране «Моя
 * учётная запись».
 */
export function PeoplePage() {
  const bootstrap = useQuery(bootstrapQueryOptions());
  const me = bootstrap.data?.account ?? null;
  const admin = me?.is_admin === true;
  const accounts = useInfiniteQuery({ ...accountsQueryOptions(), enabled: admin });
  const [flow, setFlow] = useState<Flow>({ kind: 'none' });
  const { t } = useTranslation('people');
  const { t: brick } = useTranslation('ui');
  const listId = useId();

  const items = accounts.data?.pages.flatMap((page) => page.items) ?? [];
  const close = () => setFlow({ kind: 'none' });

  return (
    <main className="flex max-w-(--ui-page-max) flex-col gap-6">
      <div>
        <h1 className="text-title">{brick('app.people')}</h1>
        <p className="mt-1 max-w-(--ui-text-max) text-meta text-muted">{t('intro')}</p>
      </div>

      <QueryState query={bootstrap} loading={t('loadingMe')} compact />

      {/* Пока флаг неизвестен, не говорится ничего: «закрыто» о неизвестном — выдумка. */}
      {bootstrap.data === undefined || admin ? null : <Callout>{t('notAdmin')}</Callout>}

      {admin ? (
        <section aria-labelledby={listId} className="flex min-w-0 flex-col gap-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 id={listId} className="text-screen">
              {t('list.title')}
            </h2>
            <Button onClick={() => setFlow({ kind: 'create' })}>{t('create.open')}</Button>
          </div>
          <p className="max-w-(--ui-text-max) text-meta text-muted">{t('list.intro')}</p>

          <QueryState
            query={accounts}
            loading={t('list.loading')}
            empty={items.length === 0 ? t('list.empty') : undefined}
          />

          <ul className="flex list-none flex-col gap-2 p-0">
            {items.map((account) => {
              const own = me !== null && account.id === me.id;
              return (
                <li key={account.id}>
                  <AccountItem
                    account={account}
                    current={own}
                    actions={
                      own ? undefined : (
                        <>
                          {isDisabled(account) ? null : (
                            <Button
                              tone="quiet"
                              className="px-2 py-1 text-meta"
                              onClick={() => setFlow({ kind: 'reset', account })}
                            >
                              {t('reset.action')}
                            </Button>
                          )}
                          <Button
                            tone="quiet"
                            className="px-2 py-1 text-meta"
                            onClick={() => setFlow({ kind: 'toggle', account })}
                          >
                            {isDisabled(account) ? t('enable.action') : t('disable.action')}
                          </Button>
                        </>
                      )
                    }
                  />
                </li>
              );
            })}
          </ul>

          {accounts.hasNextPage ? (
            <div>
              <Button
                tone="quiet"
                onClick={() => void accounts.fetchNextPage()}
                disabled={accounts.isFetchingNextPage}
              >
                {accounts.isFetchingNextPage ? t('list.loadingMore') : t('list.more')}
              </Button>
            </div>
          ) : null}
        </section>
      ) : null}

      {flow.kind === 'create' ? (
        <CreateDialog
          onClose={close}
          onCreated={(created) =>
            // Вписанный пароль администратор знает сам — окна «один раз» ему не нужно.
            setFlow(
              created.password === null || created.password === undefined
                ? { kind: 'none' }
                : {
                    kind: 'password',
                    email: created.email,
                    password: created.password,
                    reset: false,
                  },
            )
          }
        />
      ) : null}

      {flow.kind === 'reset' ? (
        <ResetDialog
          account={flow.account}
          onClose={close}
          onReset={(answer) =>
            setFlow(
              answer.password === null || answer.password === undefined
                ? { kind: 'none' }
                : { kind: 'password', email: answer.email, password: answer.password, reset: true },
            )
          }
        />
      ) : null}

      {flow.kind === 'password' ? (
        <PasswordDialog
          email={flow.email}
          password={flow.password}
          reset={flow.reset}
          onClose={close}
        />
      ) : null}

      {flow.kind === 'toggle' ? <DisableDialog account={flow.account} onClose={close} /> : null}
    </main>
  );
}
