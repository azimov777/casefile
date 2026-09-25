import { ApiError } from '../api';

/**
 * Поля, на которые жалуется отказ.
 *
 * Источников два, и оба приходят от бэкенда: `details.fields` — замечания предметной
 * области (`../docs/ERRORS.md`), `details.errors` — разбор схемы запроса
 * (`validation_error`, форма Pydantic, где имя поля стоит последним куском `loc`).
 * Имя поля, найденное здесь, только **находит** объяснение в словаре — сам текст
 * объяснения пишет экран: что значит «имя не подошло», знает он, а не отказ.
 *
 * Живёт в `shared`, а не у одного экрана: доступы и окна проекта разбирают отказ
 * одинаково, а срезы `features` друг у друга брать не вправе.
 */
export function invalidFields(error: unknown): string[] {
  if (!(error instanceof ApiError)) return [];

  const fromDomain = Object.keys(error.fields ?? {});
  const fromSchema = schemaErrors(error).flatMap((entry) => {
    const location = Array.isArray(entry.loc) ? entry.loc : [];
    const field = location.at(-1);
    return typeof field === 'string' ? [field] : [];
  });

  return [...new Set([...fromDomain, ...fromSchema])];
}

/** Жалуется ли отказ на это поле. */
export function complainsAbout(error: unknown, field: string): boolean {
  return invalidFields(error).includes(field);
}

function schemaErrors(error: ApiError): { loc?: unknown }[] {
  const errors = error.details.errors;
  return Array.isArray(errors) ? (errors as { loc?: unknown }[]) : [];
}
