import { useMutation } from '@tanstack/react-query';
import { resetSessionExpiry } from '@/entities/session';
import { ApiError, apiClient, CLIENT_ERROR_CODES, reloadInstallToken, unwrap } from '@/shared/api';

/**
 * Вход паролем владельца на установке, закрытой замком (`TRK-90`).
 *
 * Две ступени, и обе обязательны. Сначала `POST /api/v1/session`: бэкенд проверяет пароль
 * и ставит куку сеанса — скрипт страницы её не видит, её шлёт браузер. Затем установку
 * спрашивают заново (`reloadInstallToken`): с кукой `/config.json` отдаёт ключ, и дальше
 * вкладка работает им, как на локальной установке. Своего хранилища у пароля нет:
 * ни пароль, ни ключ не оседают в `localStorage`.
 *
 * Установка, принявшая пароль и всё равно не давшая ключа, — отказ с причиной, а не
 * тихий возврат на тот же экран: иначе человек вводил бы верный пароль по кругу.
 */
/**
 * Почта, которой входит форма с одним полем пароля, до экрана входа учётной записью.
 *
 * Бэкенд с `TRK-113` входит почтой и паролем, а форма спрашивает только пароль. Паролем
 * без почты входила одна учётная запись — владельца установки, закрытой
 * `TRACKER_PASSWORD_HASH`; после обновления это администратор `owner@localhost`. Поле почты
 * и ключ из ответа входа вместо `/config.json` — задача `UI-122`, и эта константа уходит с ней.
 */
const LEGACY_OWNER_EMAIL = 'owner@localhost';

export function usePasswordLogin() {
  return useMutation<string, Error, string>({
    mutationFn: async (password: string) => {
      await unwrap(
        apiClient.POST('/api/v1/session', { body: { email: LEGACY_OWNER_EMAIL, password } }),
      );
      const token = await reloadInstallToken();
      if (token === null) {
        throw new ApiError(
          CLIENT_ERROR_CODES.installKeyMissing,
          'The password was accepted, but /config.json gave no key',
          200,
          {},
        );
      }
      return token;
    },
    onSuccess: () => {
      resetSessionExpiry();
    },
  });
}
