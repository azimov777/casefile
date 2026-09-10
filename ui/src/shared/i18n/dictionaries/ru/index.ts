import { errors } from './errors';
import { login } from './login';
import { ui } from './ui';

/** Русский словарь: набор ключей обязан совпадать с английским (`dictionaries.test.ts`). */
export const ru = { errors, login, ui } as const;
