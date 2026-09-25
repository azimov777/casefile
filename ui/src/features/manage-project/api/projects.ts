import { apiClient, unwrap, type components } from '@/shared/api';

export type Project = components['schemas']['ProjectRead'];
export type Attribute = components['schemas']['AttributeRead'];
export type Entry = components['schemas']['EntryRead'];

export interface CreateProjectInput {
  key: string;
  title: string;
  description: string;
  /** Ключ повтора: тот же на каждой попытке завести этот проект. */
  idempotencyKey: string;
}

/**
 * Заводит проект. Требует набора `main` (`../docs/CONCEPT.md`, 3.2, права).
 *
 * Ключ уходит как набран: регистр приводит бэкенд, и он же проверяет образец —
 * схемой (`422 validation_error` с `loc` у поля `key`), а занятость — отказом
 * `409 project_key_taken`. Вторая копия правила на клиенте разошлась бы с первой молча.
 */
export function createProject({
  key,
  title,
  description,
  idempotencyKey,
}: CreateProjectInput): Promise<Project> {
  return unwrap(
    apiClient.POST('/api/v1/projects', {
      params: { header: { 'Idempotency-Key': idempotencyKey } },
      body: { key, title, description },
    }),
  );
}

export interface UpdateProjectInput {
  key: string;
  title: string;
  description: string;
}

/**
 * Меняет название и описание. Требует набора `main`. Ключа у правки нет и не будет:
 * он вшит в ключ каждой задачи проекта.
 *
 * Ключа повтора у правки нет — контракт его не принимает: повтор той же правки
 * ничего не меняет второй раз.
 */
export function updateProject({ key, title, description }: UpdateProjectInput): Promise<Project> {
  return unwrap(
    apiClient.PATCH('/api/v1/projects/{project_key}', {
      params: { path: { project_key: key } },
      body: { title, description },
    }),
  );
}

export interface SetAttributeInput {
  projectKey: string;
  name: string;
  value: string;
  /** Причина: обязательна при изменении, у заведения её нет (`null`). */
  reason: string | null;
  idempotencyKey: string;
}

/**
 * Заводит атрибут или меняет его значение. Набор `task` достаточен (решение 7
 * `TRK-150`): атрибут — такой же факт дела, как запись.
 *
 * Имя идёт в адрес: `openapi-fetch` кодирует его сам, а образец имени проверяет
 * бэкенд (`invalid_attribute_name`).
 */
export function setAttribute({
  projectKey,
  name,
  value,
  reason,
  idempotencyKey,
}: SetAttributeInput): Promise<Attribute> {
  return unwrap(
    apiClient.PUT('/api/v1/projects/{project_key}/attributes/{attribute_name}', {
      params: {
        path: { project_key: projectKey, attribute_name: name },
        header: { 'Idempotency-Key': idempotencyKey },
      },
      body: reason === null ? { value } : { value, reason },
    }),
  );
}

export interface RemoveAttributeInput {
  projectKey: string;
  name: string;
  reason: string;
  idempotencyKey: string;
}

/** Снимает атрибут с причиной; в ответе — подшитая запись `attribute_removed`. */
export function removeAttribute({
  projectKey,
  name,
  reason,
  idempotencyKey,
}: RemoveAttributeInput): Promise<Entry> {
  return unwrap(
    apiClient.POST('/api/v1/projects/{project_key}/attributes/{attribute_name}/remove', {
      params: {
        path: { project_key: projectKey, attribute_name: name },
        header: { 'Idempotency-Key': idempotencyKey },
      },
      body: { reason },
    }),
  );
}

export interface NoteInput {
  projectKey: string;
  title: string;
  body: string;
  idempotencyKey: string;
}

/**
 * Заметка человека в дело проекта: запись `note`. Из четырёх типов записей дела
 * проекта человеку дана одна — заметка (`UI-175`); решения, находки и артефакты
 * подшивают агенты.
 */
export function fileNote({ projectKey, title, body, idempotencyKey }: NoteInput): Promise<Entry> {
  return unwrap(
    apiClient.POST('/api/v1/projects/{project_key}/entries', {
      params: {
        path: { project_key: projectKey },
        header: { 'Idempotency-Key': idempotencyKey },
      },
      body: { type: 'note', title, body },
    }),
  );
}
