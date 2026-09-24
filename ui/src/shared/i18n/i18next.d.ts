import 'i18next';
import type { en } from './dictionaries/en';

/**
 * Ключи переводов проверяет компилятор: опечатка в `t('…')` и ключ, забытый в словаре
 * по умолчанию, становятся ошибкой сборки, а не пустой строкой на экране. Ровно та же
 * дисциплина, по которой живёт `shared/errors`: расхождение обязано ронять `pnpm check`.
 *
 * Типы берутся с английского словаря, потому что английский — язык по умолчанию.
 * Полноту остальных языков компилятор не видит: их набор ключей сверяет
 * `dictionaries/dictionaries.test.ts`.
 *
 * Пространства `errors` и `fieldReasons` объявлены как `Record<string, string>`
 * намеренно: их ключи — коды бэкенда (`error.code` и `details.fields[].reason`),
 * приезжающие в рантайме, и требовать от компилятора списка кодов значит требовать,
 * чтобы клиент знал контракт наизусть. Полноту `errors` проверяет
 * `shared/errors/text.test.ts` против `../docs/ERRORS.md` — то есть против источника,
 * а не против нашей памяти. У `fieldReasons` такого источника нет (`ru/field-reasons.ts`),
 * и полноту с ним никто не сверяет: причина без перевода показывает запасной текст.
 */
declare module 'i18next' {
  interface CustomTypeOptions {
    defaultNS: 'ui';
    // `defaultValue` не должен превращать несуществующий ключ в законный вызов.
    strictKeyChecks: true;
    resources: Omit<typeof en, 'errors' | 'fieldReasons'> & {
      errors: Record<string, string>;
      fieldReasons: Record<string, string>;
    };
  }
}
