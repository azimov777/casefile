import { access } from './access';
import { caseScreen } from './case';
import { connect } from './connect';
import { errors } from './errors';
import { login } from './login';
import { questions } from './questions';
import { task } from './task';
import { tasks } from './tasks';
import { ui } from './ui';

/** Русский словарь: набор ключей обязан совпадать с английским (`dictionaries.test.ts`). */
export const ru = {
  access,
  case: caseScreen,
  connect,
  errors,
  login,
  questions,
  task,
  tasks,
  ui,
} as const;
