import { useTranslation } from 'react-i18next';
import { Callout } from '@/shared/ui';

/**
 * Сброс прямо в предложении: человек уже читает, почему записи не видно, и второй раз
 * искать то же условие глазами он не должен. Фон и граница названы явно: у `<button>`
 * без объявленного фона браузер рисует свой `ButtonFace` (`docs/notes/ui.md`).
 */
const INLINE_RESET = 'border-none bg-transparent p-0 text-accent underline';

/**
 * Запись из адреса не попала в отобранную выдачу: сказано словами, со сбросом отбора.
 * Те же слова, что на экране «Дело» задачи, — для дела проекта и направления (TRK-621).
 */
export function HiddenByTypeNotice({
  reference,
  onReset,
}: {
  reference: string;
  onReset: () => void;
}) {
  const { t } = useTranslation('case');
  return (
    <Callout>
      {t('window.hiddenByType', { reference })}{' '}
      <button type="button" className={INLINE_RESET} onClick={onReset}>
        {t('window.showAllTypes')}
      </button>
    </Callout>
  );
}

/** Отбор по типу ничего не нашёл: честное пустое состояние, сброс — в строке фильтра. */
export function EmptyByTypesNotice() {
  const { t } = useTranslation('case');
  return <Callout>{t('emptyByTypes')}</Callout>;
}
