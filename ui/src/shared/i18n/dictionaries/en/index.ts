import { caseScreen } from './case';
import { errors } from './errors';
import { login } from './login';
import { questions } from './questions';
import { task } from './task';
import { tasks } from './tasks';
import { ui } from './ui';

/**
 * Английский словарь: он же источник типов ключей (`../../i18next.d.ts`), потому что
 * английский — язык по умолчанию. Ключ, пропавший отсюда, становится ошибкой сборки
 * в каждом месте, где его звали.
 *
 * Новое пространство имён добавляется двумя строками — импортом и полем; их набор
 * задан программой UI-76: `login`, `tasks`, `task`, `case`, `questions`, `errors`, `ui`.
 *
 * Пространство `case` названо в файле `caseScreen`: `case` — ключевое слово, и
 * переменной с таким именем не бывает. Имя пространства при этом `case` — оно живёт
 * ключом объекта, а не именем переменной.
 */
export const en = { case: caseScreen, errors, login, questions, task, tasks, ui } as const;
