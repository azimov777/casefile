import { access } from './access';
import { account } from './account';
import { caseScreen } from './case';
import { connect } from './connect';
import { area } from './area';
import { errors } from './errors';
import { fieldReasons } from './field-reasons';
import { login } from './login';
import { moving } from './moving';
import { people } from './people';
import { project } from './project';
import { questions } from './questions';
import { start } from './start';
import { task } from './task';
import { tasks } from './tasks';
import { ui } from './ui';

/** Русский словарь: набор ключей обязан совпадать с английским (`dictionaries.test.ts`). */
export const ru = {
  access,
  account,
  case: caseScreen,
  connect,
  area,
  errors,
  fieldReasons,
  login,
  moving,
  people,
  project,
  questions,
  start,
  task,
  tasks,
  ui,
} as const;
