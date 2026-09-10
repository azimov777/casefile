import i18next from 'i18next';
import LanguageDetector from 'i18next-browser-languagedetector';
import { initReactI18next } from 'react-i18next';
import { dictionaries } from './dictionaries';
import {
  DEFAULT_LANGUAGE,
  LANGUAGES,
  LANGUAGE_STORAGE_KEY,
  isLanguage,
  type Language,
} from './languages';

/*
 * Единственный экземпляр `i18next` на приложение: он же отвечает на вопрос «какой
 * сейчас язык» коду вне компонентов (`shared/errors`).
 *
 * Инициализация — побочное действие импорта, и это не небрежность: словари вшиты
 * в сборку, грузить нечего, а провайдер обязан получить готовый экземпляр к первому
 * кадру. Асинхронная инициализация дала бы кадр без подписей.
 */
void i18next
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources: dictionaries,
    // Пространства перечислены словарём, а не списком рядом: список разошёлся бы с ним
    // ровно в тот день, когда UI-78 добавит своё.
    ns: Object.keys(dictionaries[DEFAULT_LANGUAGE]),
    defaultNS: 'ui',
    supportedLngs: LANGUAGES,
    /*
     * Область отбрасывается: `ru-RU`, `ru-BY` и `ru` — один словарь. Без этого браузер
     * с `ru-RU` не нашёл бы ни одного ключа и уехал бы в запасной английский.
     */
    load: 'languageOnly',
    fallbackLng: DEFAULT_LANGUAGE,
    /*
     * Порядок выбора языка задан программой UI-76: выбор человека в хранилище →
     * язык браузера → английский. Последняя ступень — это `fallbackLng`, а не третий
     * определитель: `navigator` вернёт языки, которых мы не знаем, и `supportedLngs`
     * отправит их в запасной.
     *
     * `caches` записывает язык в то же хранилище при каждой смене. Следствие названо
     * сознательно: первый визит запоминает язык браузера, и человек, сменивший его
     * потом в браузере, останется на прежнем, пока не выберет новый здесь.
     */
    detection: {
      order: ['localStorage', 'navigator'],
      caches: ['localStorage'],
      lookupLocalStorage: LANGUAGE_STORAGE_KEY,
    },
    // React экранирует сам; двойное экранирование превратило бы кавычки в `&quot;`.
    interpolation: { escapeValue: false },
    // Грузить нечего, поэтому язык встаёт до первой отрисовки, а не после неё.
    initAsync: false,
    // Загрузки нет — значит нет и ожидания, ради которого нужен `Suspense`.
    react: { useSuspense: false },
  });

export const i18n = i18next;

/** Текущий язык интерфейса вне компонентов. Внутри них — `useLanguage`. */
export function currentLanguage(): Language {
  return isLanguage(i18n.resolvedLanguage) ? i18n.resolvedLanguage : DEFAULT_LANGUAGE;
}

/**
 * Выбор человека: язык меняется на месте и запоминается в хранилище определителем.
 *
 * Перезагрузки здесь нет и быть не может: `window.location.reload()` после смены языка
 * — признак того, что язык прочитан однажды при старте, а не встроен в отрисовку.
 * Набранный в поле текст, раскрытый отбор и положение прокрутки обязаны остаться
 * на месте.
 */
export function setLanguage(language: Language): void {
  void i18n.changeLanguage(language);
}
