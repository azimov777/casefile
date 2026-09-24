import { access } from './access';
import { account } from './account';
import { caseScreen } from './case';
import { connect } from './connect';
import { errors } from './errors';
import { fieldReasons } from './field-reasons';
import { login } from './login';
import { moving } from './moving';
import { people } from './people';
import { project } from './project';
import { questions } from './questions';
import { task } from './task';
import { tasks } from './tasks';
import { ui } from './ui';

/** Русский словарь: набор ключей обязан совпадать с английским (`dictionaries.test.ts`). */
export const ru = {
  access,
  account,
  case: caseScreen,
  connect,
  errors,
  fieldReasons,
  login,
  moving,
  people,
  project,
  questions,
  task,
  tasks,
  ui,
} as const;
