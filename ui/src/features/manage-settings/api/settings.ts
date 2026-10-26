import { apiClient, unwrap } from '@/shared/api';
import type { Setting } from '@/entities/setting';

/**
 * Задаёт значение настройки установки или возвращает её окружению: `null` — «брать из
 * окружения» (пустая строка значила бы то же, но `null` читается прямо). Только
 * администратору (`403 admin_required`); значение вне типа или пределов —
 * `422 installation_setting_invalid` с причиной в `details.reason`, и ничего не меняется.
 *
 * Ключа повтора нет: правка идемпотентна по смыслу — повтор кладёт то же значение.
 */
export function updateSetting(name: string, value: string | null): Promise<Setting> {
  return unwrap(
    apiClient.PATCH('/api/v1/settings/{name}', {
      params: { path: { name } },
      body: { value },
    }),
  );
}
