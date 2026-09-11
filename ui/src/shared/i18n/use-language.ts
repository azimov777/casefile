import { useTranslation } from 'react-i18next';
import { currentLanguage, setLanguage } from './i18n';
import type { Language } from './languages';

/**
 * Текущий язык и способ его сменить.
 *
 * Через `useTranslation`, а не чтением из экземпляра: подписка на смену языка нужна
 * ровно для того, чтобы переключатель перерисовался вместе со всем остальным.
 */
export function useLanguage(): { language: Language; setLanguage: (next: Language) => void } {
  useTranslation();
  return { language: currentLanguage(), setLanguage };
}
