import { useId, useState } from 'react';
import { useInfiniteQuery, useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { AccountItem, accountsQueryOptions, isDisabled } from '@/entities/account';
import { bootstrapQueryOptions } from '@/entities/session';
import { CreateDialog, DisableDialog, PasswordDialog, ResetDialog } from '@/features/manage-people';
import { Button, Callout, QueryState } from '@/shared/ui';

/**
 * Пароль, который трекер показывает один раз, — единственное, что осталось общим
 * состоянием страницы: открывает его не кнопка, а ход работы (успешное заведение или
 * сброс), и триггера у такого окна нет (`UI-175#11`, тот же случай, что у секрета
 * токена на экране «Доступы»; фокус для таких окон — отдельное решение, вне этой
 * задачи). Заведение — своей кнопкой на весь экран (`UI-175`); сброс и отключение —
 * своей кнопкой на каждой карточке, с состоянием открытия внутри неё же (`UI-178`):
 * иначе Radix закрывал бы общее на всех окно, не зная, в какую из карточек вернуть
 * фокус (`UI-175#11`).
 *
 * Пароль живёт здесь, в состоянии экрана, и нигде больше: ни в адресе, ни в
 * хранилищах браузера, ни в кэше запросов. Закрытие окна стирает его.
 */
interface Once {
  email: string;
  password: string;
  /** Пароль после сброса, а не при заведении: другой заголовок у окна. */
  reset: boolean;
}

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
  const [createOpen, setCreateOpen] = useState(false);
  const [once, setOnce] = useState<Once | null>(null);
  const { t } = useTranslation('people');
  const { t: brick } = useTranslation('ui');
  const listId = useId();

  const items = accounts.data?.pages.flatMap((page) => page.items) ?? [];

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
            <CreateDialog
              open={createOpen}
              onOpenChange={setCreateOpen}
              trigger={<Button>{t('create.open')}</Button>}
              onCreated={(created) => {
                setCreateOpen(false);
                // Вписанный пароль администратор знает сам — окна «один раз» ему не нужно.
                if (created.password !== null && created.password !== undefined) {
                  setOnce({ email: created.email, password: created.password, reset: false });
                }
              }}
            />
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
                            <ResetDialog
                              account={account}
                              onReset={(answer) => {
                                // Вписанный пароль администратор знает сам — окна «один
                                // раз» ему не нужно.
                                if (answer.password !== null && answer.password !== undefined) {
                                  setOnce({
                                    email: answer.email,
                                    password: answer.password,
                                    reset: true,
                                  });
                                }
                              }}
                            />
                          )}
                          <DisableDialog account={account} />
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

      {/* Окно пароля — по-прежнему только по `once`: открывает его не кнопка, а ход
          работы (успешное заведение или сброс), и триггера у него нет (`UI-175#11`,
          тот же случай, что у секрета токена на экране «Доступы»; фокус для таких
          окон — отдельное решение, вне этой задачи). */}
      {once === null ? null : (
        <PasswordDialog
          email={once.email}
          password={once.password}
          reset={once.reset}
          onClose={() => setOnce(null)}
        />
      )}
    </main>
  );
}
