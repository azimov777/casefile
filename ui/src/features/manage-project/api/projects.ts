import { apiClient, unwrap, type components } from '@/shared/api';
import { splitAreaAddress } from '@/shared/lib';

export type Project = components['schemas']['ProjectRead'];
export type Attribute = components['schemas']['AttributeRead'];
export type Entry = components['schemas']['EntryRead'];
export type Area = components['schemas']['AreaRead'];
export type AreaDetail = components['schemas']['AreaDetailRead'];

/**
 * Чьи атрибуты и дело: проект или его область (TRK-557). Область устроена как
 * проект, только меньше (`../docs/CONCEPT.md`, 3.7): атрибуты и записи у них — одни
 * правила и одни сценарии бэкенда, различается только путь. Ключ области — её
 * адрес `TRK/promotion`; путь API собирается из двух его частей.
 */
export interface Holder {
  kind: 'project' | 'area';
  key: string;
}

/** Путь области в API: ключ проекта и ключ области двумя сегментами. */
function areaPath(address: string) {
  const { projectKey, areaKey } = splitAreaAddress(address);
  return { project_key: projectKey, area_key: areaKey };
}

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
  holder: Holder;
  name: string;
  value: string;
  /** Причина: обязательна при изменении, у заведения её нет (`null`). */
  reason: string | null;
  idempotencyKey: string;
}

/**
 * Заводит атрибут или меняет его значение — у проекта или у области. Набор `task`
 * достаточен (решение 7 `TRK-150`): атрибут — такой же факт дела, как запись.
 *
 * Имя идёт в адрес: `openapi-fetch` кодирует его сам, а образец имени проверяет
 * бэкенд (`invalid_attribute_name`).
 */
export function setAttribute({
  holder,
  name,
  value,
  reason,
  idempotencyKey,
}: SetAttributeInput): Promise<Attribute> {
  const body = reason === null ? { value } : { value, reason };
  const header = { 'Idempotency-Key': idempotencyKey };
  return holder.kind === 'area'
    ? unwrap(
        apiClient.PUT(
          '/api/v1/projects/{project_key}/areas/{area_key}/attributes/{attribute_name}',
          {
            params: { path: { ...areaPath(holder.key), attribute_name: name }, header },
            body,
          },
        ),
      )
    : unwrap(
        apiClient.PUT('/api/v1/projects/{project_key}/attributes/{attribute_name}', {
          params: { path: { project_key: holder.key, attribute_name: name }, header },
          body,
        }),
      );
}

export interface RemoveAttributeInput {
  holder: Holder;
  name: string;
  reason: string;
  idempotencyKey: string;
}

/** Снимает атрибут с причиной; в ответе — подшитая запись `attribute_removed`. */
export function removeAttribute({
  holder,
  name,
  reason,
  idempotencyKey,
}: RemoveAttributeInput): Promise<Entry> {
  const header = { 'Idempotency-Key': idempotencyKey };
  return holder.kind === 'area'
    ? unwrap(
        apiClient.POST(
          '/api/v1/projects/{project_key}/areas/{area_key}/attributes/{attribute_name}/remove',
          {
            params: { path: { ...areaPath(holder.key), attribute_name: name }, header },
            body: { reason },
          },
        ),
      )
    : unwrap(
        apiClient.POST('/api/v1/projects/{project_key}/attributes/{attribute_name}/remove', {
          params: { path: { project_key: holder.key, attribute_name: name }, header },
          body: { reason },
        }),
      );
}

/**
 * Какие записи человек пишет в дело: в дело проекта — только заметку (`UI-175`; решения,
 * находки и артефакты подшивают агенты), в дело области — заметку и решение
 * (TRK#16, ч. 4: «человек пишет заметки и решения»; запись `decision` в деле TRK-557).
 */
export type HumanEntryType = 'note' | 'decision';

export interface EntryInput {
  holder: Holder;
  type: HumanEntryType;
  title: string;
  body: string;
  idempotencyKey: string;
}

/**
 * Запись человека в дело проекта или области. У области `supersedes` нет вовсе:
 * механика замены решений проекта на её дело не распространяется (TRK-555).
 */
export function fileEntry({
  holder,
  type,
  title,
  body,
  idempotencyKey,
}: EntryInput): Promise<Entry> {
  const header = { 'Idempotency-Key': idempotencyKey };
  return holder.kind === 'area'
    ? unwrap(
        apiClient.POST('/api/v1/projects/{project_key}/areas/{area_key}/entries', {
          params: { path: areaPath(holder.key), header },
          body: { type, title, body },
        }),
      )
    : unwrap(
        apiClient.POST('/api/v1/projects/{project_key}/entries', {
          params: { path: { project_key: holder.key }, header },
          body: { type, title, body },
        }),
      );
}

export type ProjectDetail = components['schemas']['ProjectDetailRead'];

export interface ArchivingInput {
  key: string;
  /** Почему проект уходит в архив или возвращается из него; пустой бэкенд не примет. */
  reason: string;
}

/**
 * Архивирует проект с причиной (`UI-176`, `../docs/CONCEPT.md`, 3.2). Требует набора
 * `main`. Проект и его задачи замораживаются как есть; причина уезжает в запись
 * `archived` дела проекта.
 *
 * Ключа повтора у архива нет — контракт его не принимает: повтор отвечает
 * `project_archived`, а не второй записью.
 */
export function archiveProject({ key, reason }: ArchivingInput): Promise<ProjectDetail> {
  return unwrap(
    apiClient.POST('/api/v1/projects/{project_key}/archive', {
      params: { path: { project_key: key } },
      body: { reason },
    }),
  );
}

/** Восстанавливает проект из архива с причиной; задачи продолжаются с того же места. */
export function restoreProject({ key, reason }: ArchivingInput): Promise<ProjectDetail> {
  return unwrap(
    apiClient.POST('/api/v1/projects/{project_key}/restore', {
      params: { path: { project_key: key } },
      body: { reason },
    }),
  );
}

export interface CreateAreaInput {
  projectKey: string;
  key: string;
  title: string;
  description: string;
  /** Ключ повтора: тот же на каждой попытке завести эту область. */
  idempotencyKey: string;
}

/**
 * Заводит область в проекте (TRK-557, `../docs/CONCEPT.md`, 3.7). Ключ уходит как
 * набран: регистр приводит бэкенд, он же проверяет образец (`422 invalid_area_key`)
 * и занятость в проекте (`409 area_key_taken`).
 */
export function createArea({
  projectKey,
  key,
  title,
  description,
  idempotencyKey,
}: CreateAreaInput): Promise<Area> {
  return unwrap(
    apiClient.POST('/api/v1/projects/{project_key}/areas', {
      params: { path: { project_key: projectKey }, header: { 'Idempotency-Key': idempotencyKey } },
      body: { key, title, description },
    }),
  );
}

export interface UpdateAreaInput {
  /** Адрес области `TRK/promotion`. */
  address: string;
  title: string;
  description: string;
}

/** Меняет название и описание области. Ключа у правки нет: он вшит в адрес. */
export function updateArea({ address, title, description }: UpdateAreaInput): Promise<AreaDetail> {
  return unwrap(
    apiClient.PATCH('/api/v1/projects/{project_key}/areas/{area_key}', {
      params: { path: areaPath(address) },
      body: { title, description },
    }),
  );
}

export interface AreaArchivingInput {
  address: string;
  /** Почему область уходит в архив или возвращается; пустую бэкенд не примет. */
  reason: string;
}

/**
 * Архивирует область с причиной: карточка, атрибуты и дело замораживаются, новую
 * задачу в неё не поставить; задачи, что уже в ней, работают как обычно.
 */
export function archiveArea({ address, reason }: AreaArchivingInput): Promise<AreaDetail> {
  return unwrap(
    apiClient.POST('/api/v1/projects/{project_key}/areas/{area_key}/archive', {
      params: { path: areaPath(address) },
      body: { reason },
    }),
  );
}

/** Восстанавливает область из архива с причиной. */
export function restoreArea({ address, reason }: AreaArchivingInput): Promise<AreaDetail> {
  return unwrap(
    apiClient.POST('/api/v1/projects/{project_key}/areas/{area_key}/restore', {
      params: { path: areaPath(address) },
      body: { reason },
    }),
  );
}
