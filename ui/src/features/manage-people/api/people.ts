import { apiClient, unwrap, type components, type operations } from '@/shared/api';
import type { Account } from '@/entities/account';

/**
 * Учётная запись вместе с паролем, который трекер сгенерировал: единственные ответы
 * контракта, где пароль виден (`POST /accounts` и `POST /accounts/{id}/password-reset`).
 * Вписанный администратором пароль обратно не приезжает — там `password: null`.
 */
export type AccountWithPassword = components['schemas']['AccountWithPasswordRead'];

type CreateBody = NonNullable<
  operations['create_account']['requestBody']
>['content']['application/json'];

export interface CreateInput {
  email: string;
  /** Имя участника: им подписаны записи человека, и дальше оно неизменяемо. */
  name: string;
  isAdmin: boolean;
  /** Вписанный пароль или `null` — тогда пароль генерирует трекер и отдаёт один раз. */
  password: string | null;
}

/**
 * Заводит учётную запись человеку. Только администратору (`403 admin_required`).
 *
 * Ключа повтора нет намеренно (UI-122#9): вторую запись с той же почтой не даст
 * уникальность (`409 account_email_taken`), а пароль, потерянный на обрыве сети,
 * возвращается сбросом. Повтор с ключом отдавал бы тот же пароль ещё раз — то есть
 * ключ стоил бы самого пароля, и его пришлось бы беречь так же.
 */
export function createAccount({
  email,
  name,
  isAdmin,
  password,
}: CreateInput): Promise<AccountWithPassword> {
  const body: CreateBody = {
    email: email.trim(),
    name: name.trim(),
    // Описание нового участника контракт принимает, но экран его не спрашивает: человек
    // здесь — учётная запись, а не агент, которого описывают для соседей.
    description: '',
    is_admin: isAdmin,
    ...(password === null ? {} : { password }),
  };
  return unwrap(apiClient.POST('/api/v1/accounts', { body }));
}

/**
 * Новый пароль учётной записи — вписанный или сгенерированный. Гасит все сеансы этого
 * человека: вошедший со старым паролем выйдет на следующем же запросе.
 */
export function resetPassword(
  accountId: string,
  password: string | null,
): Promise<AccountWithPassword> {
  return unwrap(
    apiClient.POST('/api/v1/accounts/{account_id}/password-reset', {
      params: { path: { account_id: accountId } },
      body: password === null ? {} : { password },
    }),
  );
}

/**
 * Отключает или включает учётную запись. Отключение закрывает вход и отзывает **все**
 * токены её участника — и сеансы, и выпущенные его агентам; включение пускает снова,
 * но отозванное остаётся отозванным. Последнего действующего администратора отключить
 * нельзя: `409 last_admin`.
 */
export function setDisabled(accountId: string, disabled: boolean): Promise<Account> {
  return unwrap(
    apiClient.PATCH('/api/v1/accounts/{account_id}', {
      params: { path: { account_id: accountId } },
      body: { disabled },
    }),
  );
}
