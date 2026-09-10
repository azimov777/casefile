import { useTranslation } from 'react-i18next';
import { LANGUAGES, LANGUAGE_NAMES, isLanguage, useLanguage } from '@/shared/i18n';
import { Select } from '@/shared/ui';

/**
 * Переключатель языка интерфейса.
 *
 * Названия языков не переводятся: в списке всегда `English` и `Русский`, каждое на
 * своём языке (`shared/i18n/languages.ts`). Человек, открывший список на непонятном ему
 * языке, обязан узнать там свой — это единственное место, где кириллица в разметке
 * законна.
 *
 * Смена языка ничего не перезагружает: набранный в поле токен, раскрытый отбор
 * и положение прокрутки остаются на месте.
 */
export function LanguageSwitch({ className }: { className?: string }) {
  const { t } = useTranslation();
  const { language, setLanguage } = useLanguage();

  return (
    <Select
      value={language}
      onValueChange={(next) => {
        // `Select` отдаёт строку — он не знает про наши языки; сузить её надо здесь.
        if (isLanguage(next)) setLanguage(next);
      }}
      label={t('language')}
      options={LANGUAGES.map((code) => ({ value: code, label: LANGUAGE_NAMES[code] }))}
      className={className}
    />
  );
}
