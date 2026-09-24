import { access } from './access';
import { account } from './account';
import { caseScreen } from './case';
import { connect } from './connect';
import { errors } from './errors';
import { fieldReasons } from './field-reasons';
import { login } from './login';
import { moving } from './moving';
import { people } from './people';
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
 * задан программой UI-76: `login`, `tasks`, `task`, `case`, `questions`, `errors`, `ui`;
 * `connect` добавила UI-105, `access` — UI-106, `account` и `people` — UI-122,
 * `moving` — UI-135, `fieldReasons` — UI-165.
 *
 * Пространство `case` названо в файле `caseScreen`: `case` — ключевое слово, и
 * переменной с таким именем не бывает. Имя пространства при этом `case` — оно живёт
 * ключом объекта, а не именем переменной.
 */
export const en = {
  access,
  account,
  case: caseScreen,
  connect,
  errors,
  fieldReasons,
  login,
  moving,
  people,
  questions,
  task,
  tasks,
  ui,
} as const;
