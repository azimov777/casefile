import { useTranslation } from 'react-i18next';
import type { Setting } from '../api/settings';
import { parseCanonical, splitAmount } from './amount';

/**
 * Значение настройки словами: `25 МБ`, `30 дн.`, `Включена`. Для незнакомого вида
 * возвращает строку как пришла — выдумывать единицы экран не берётся.
 */
export function useFormatAmount() {
  const { t } = useTranslation('settings');

  return function format(
    setting: Pick<Setting, 'name' | 'kind'>,
    canonical: string | number,
  ): string {
    if (setting.kind === 'boolean') {
      return String(canonical) === 'true' ? t('boolean.on') : t('boolean.off');
    }
    const value = typeof canonical === 'number' ? canonical : parseCanonical(setting, canonical);
    if (value === null) return String(canonical);
    const { amount, unit } = splitAmount(setting.name, value);
    return `${amount} ${t(`units.${unit.id}`)}`;
  };
}
