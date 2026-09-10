import { errors } from './errors';
import { login } from './login';
import { ui } from './ui';

/**
 * Английский словарь: он же источник типов ключей (`../../i18next.d.ts`), потому что
 * английский — язык по умолчанию. Ключ, пропавший отсюда, становится ошибкой сборки
 * в каждом месте, где его звали.
 *
 * Новое пространство имён добавляется двумя строками — импортом и полем; их набор
 * задан программой UI-76: `login`, `tasks`, `task`, `case`, `questions`, `errors`, `ui`.
 */
export const en = { errors, login, ui } as const;
