import { infiniteQueryOptions, keepPreviousData, queryOptions } from '@tanstack/react-query';
import {
  apiClient,
  unwrap,
  unwrapPage,
  type Page,
  type components,
  type operations,
} from '@/shared/api';
import { splitAreaAddress } from '@/shared/lib';
import type { EntryOwner } from '../model/owner';

/** Запись дела с телом и нагрузкой: объединение, размеченное полем `type`. */
export type Entry = components['schemas']['EntryRead'];

/** Строка описи: заголовок записи без тела. */
export type EntryHeading = components['schemas']['EntryHeadingRead'];

export type EntryType = components['schemas']['EntryType'];
export type Author = components['schemas']['AuthorRead'];

/** Параметры чтения дела — из контракта, а не свои. */
export type EntryListParams = NonNullable<operations['list_task_entries']['parameters']['query']>;

/**
 * Типы записей списком.
 *
 * Перечислены ключами объекта: `satisfies Record<EntryType, true>` требует все члены
 * объединения, поэтому новый тип записи на бэкенде роняет сборку — а не появляется
 * в ленте без своего представления (та же причина, что у `TASK_STATUSES`).
 */
const ENTRY_TYPE_SET = {
  summary: true,
  decision: true,
  attempt: true,
  finding: true,
  artifact: true,
  question: true,
  answer: true,
  verdict: true,
  remark: true,
  resolution: true,
  acceptance: true,
  conclusion: true,
  note: true,
  created: true,
  status_changed: true,
  section_changed: true,
  field_changed: true,
  assignee_changed: true,
  link_added: true,
  link_removed: true,
  moved: true,
  warning: true,
  attached: true,
  detached: true,
  closed: true,
  attribute_created: true,
  attribute_changed: true,
  attribute_removed: true,
  archived: true,
  restored: true,
} satisfies Record<EntryType, true>;

export const ENTRY_TYPES = Object.keys(ENTRY_TYPE_SET) as EntryType[];

/**
 * Служебные типы: их подшивает сам трекер, а не агент (TRK#131).
 *
 * Словарь по значению, а не список: тип, добавленный в контракт, окажется среди записей
 * агента — это верное умолчание, потому что трекер свои записи заводит редко, а разбор
 * по типам всё равно упадёт сборкой в представлении записи.
 */
const SERVICE_TYPES: Partial<Record<EntryType, true>> = {
  created: true,
  status_changed: true,
  section_changed: true,
  field_changed: true,
  assignee_changed: true,
  link_added: true,
  link_removed: true,
  moved: true,
  warning: true,
  attached: true,
  detached: true,
  closed: true,
  attribute_created: true,
  attribute_changed: true,
  attribute_removed: true,
  archived: true,
  restored: true,
};

export function isServiceEntry(type: EntryType): boolean {
  return SERVICE_TYPES[type] === true;
}

/** Сколько записей на странице ленты. */
export const ENTRY_PAGE_SIZE = 25;

export const entryKeys = {
  /** Ключ пакета карточки живёт в `entities/task`; здесь только тела. */
  bodies: (taskKey: string, nos: number[]) => ['task', taskKey, 'entries', nos] as const,
  /** Лента дела: страницы копятся, поэтому свой ключ, а не ключ тел записей. */
  feed: (taskKey: string, params: EntryListParams) => ['task', taskKey, 'case', params] as const,
  /** Тело записи дела обсуждения: под префиксом обсуждения, как тела задачи — под её. */
  discussionBody: (address: string, no: number) => ['discussion', address, 'entries', no] as const,
  /** Тело одной записи дела проекта: под префиксом проекта, как тела задачи — под её. */
  projectBody: (projectKey: string, no: number) => ['project', projectKey, 'entries', no] as const,
  /** Дело проекта страницами, с отбором по типам или без. */
  projectCase: (projectKey: string, params: ProjectEntryListParams) =>
    ['project', projectKey, 'case', params] as const,
  /**
   * Тело одной записи дела области — под префиксом области `['area',
   * адрес]`, как тела проекта под его префиксом (TRK-557).
   */
  areaBody: (address: string, no: number) => ['area', address, 'entries', no] as const,
  /** Решения и находки дела задачи: из них выбираются черновики знания (TRK-661). */
  drafts: (taskKey: string) => ['task', taskKey, 'drafts'] as const,
  /** Знание области целиком — решения и заметки, с поиском или без (TRK-660). */
  areaKnowledge: (address: string, text: string) => ['area', address, 'knowledge', text] as const,
  /** Дело области страницами, с отбором или без. */
  areaCase: (address: string, params: ProjectEntryListParams) =>
    ['area', address, 'case', params] as const,
};

/** Параметры чтения дела проекта — из контракта. */
export type ProjectEntryListParams = NonNullable<
  operations['list_project_entries']['parameters']['query']
>;

/**
 * Тело одной записи дела — задачи, проекта или области.
 *
 * Номер — часть ключа запроса, поэтому раскрытая запись читается один раз и живёт
 * в кэше: закрыть и открыть её снова второго запроса не стоит. У задачи тело читается
 * отбором `entries?nos=N` (тем же путём, что лента), у проекта и области — своим
 * адресом записи `entries/{no}`: у их дел он есть, и отбор ради одной записи был бы обходом.
 */
export function entryQueryOptions(owner: EntryOwner, no: number) {
  // Ключ объявлен общим типом: у владельцев разные префиксы (`task`, `project`,
  // `area`), а запрос один — иначе вызывающий получил бы объединение видов опций.
  const queryKey: readonly unknown[] =
    owner.kind === 'project'
      ? entryKeys.projectBody(owner.key, no)
      : owner.kind === 'area'
        ? entryKeys.areaBody(owner.key, no)
        : owner.kind === 'discussion'
          ? entryKeys.discussionBody(owner.key, no)
          : entryKeys.bodies(owner.key, [no]);
  return queryOptions({
    queryKey,
    queryFn: (): Promise<Entry | null> =>
      owner.kind === 'project'
        ? readProjectEntry(owner.key, no)
        : owner.kind === 'area'
          ? readAreaEntry(owner.key, no)
          : owner.kind === 'discussion'
            ? readDiscussionEntry(owner.key, no)
            : readTaskEntry(owner.key, no),
  });
}

async function readTaskEntry(taskKey: string, no: number): Promise<Entry | null> {
  const page = await unwrapPage(
    apiClient.GET('/api/v1/tasks/{task_key}/entries', {
      params: { path: { task_key: taskKey }, query: { nos: [no] } },
    }),
  );
  return page.items[0] ?? null;
}

async function readDiscussionEntry(address: string, no: number): Promise<Entry | null> {
  const page = await unwrapPage(
    apiClient.GET('/api/v1/discussions/{discussion}/entries', {
      params: { path: { discussion: address }, query: { nos: [no] } },
    }),
  );
  return page.items[0] ?? null;
}

function readProjectEntry(projectKey: string, no: number): Promise<Entry> {
  return unwrap(
    apiClient.GET('/api/v1/projects/{project_key}/entries/{entry_no}', {
      params: { path: { project_key: projectKey, entry_no: no } },
    }),
  );
}

function readAreaEntry(address: string, no: number): Promise<Entry> {
  const { projectKey, areaKey } = splitAreaAddress(address);
  return unwrap(
    apiClient.GET('/api/v1/projects/{project_key}/areas/{area_key}/entries/{entry_no}', {
      params: { path: { project_key: projectKey, area_key: areaKey, entry_no: no } },
    }),
  );
}

/**
 * Дело проекта одной страницы на запрос: предел контракта — 200 записей. Дело
 * проекта короткое (ни сводок, ни вопросов, ни вердиктов), и больше страницы оно
 * набирает редко, но «показать всё» и здесь не обещается: следующая страница — по
 * кнопке, курсором бэкенда.
 */
export const PROJECT_ENTRY_PAGE_SIZE = 200;

export function projectCaseQueryOptions(projectKey: string, params: ProjectEntryListParams = {}) {
  return infiniteQueryOptions({
    queryKey: entryKeys.projectCase(projectKey, params),
    queryFn: ({ pageParam }): Promise<Page<Entry>> =>
      readProjectCasePage(projectKey, params, pageParam),
    initialPageParam: '',
    getNextPageParam: nextCursor,
  });
}

/** Курсор следующей страницы дела или `undefined`, если страниц больше нет. */
function nextCursor(last: Page<Entry>): string | undefined {
  return last.meta?.has_more === true ? (last.meta.next_cursor ?? undefined) : undefined;
}

function readProjectCasePage(
  projectKey: string,
  params: ProjectEntryListParams,
  cursor: string,
): Promise<Page<Entry>> {
  return unwrapPage(
    apiClient.GET('/api/v1/projects/{project_key}/entries', {
      params: {
        path: { project_key: projectKey },
        query: {
          limit: PROJECT_ENTRY_PAGE_SIZE,
          ...params,
          cursor: cursor === '' ? undefined : cursor,
        },
      },
    }),
  );
}

function readAreaCasePage(
  address: string,
  params: ProjectEntryListParams,
  cursor: string,
): Promise<Page<Entry>> {
  const { projectKey, areaKey } = splitAreaAddress(address);
  return unwrapPage(
    apiClient.GET('/api/v1/projects/{project_key}/areas/{area_key}/entries', {
      params: {
        path: { project_key: projectKey, area_key: areaKey },
        query: {
          limit: PROJECT_ENTRY_PAGE_SIZE,
          ...params,
          cursor: cursor === '' ? undefined : cursor,
        },
      },
    }),
  );
}

/**
 * Дело проекта или области (TRK-557) — одним вызовом для разделов, которые рисуют
 * оба (`features/manage-project`, `AttributesSection`, `CaseSection`). Дело области
 * читается так же, как дело проекта: одна страница до 200 записей на запрос, следующая по
 * кнопке, те же отборы, включая историю одного атрибута (`attribute`), — бэкенд читает оба
 * дела одним сценарием.
 *
 * Ключ объявлен общим типом по той же причине, что у `entryQueryOptions`: префиксы у
 * владельцев разные (`project`, `area`), а запрос один.
 */
export function holderCaseQueryOptions(
  holder: { kind: 'project' | 'area'; key: string },
  params: ProjectEntryListParams = {},
) {
  const queryKey: readonly unknown[] =
    holder.kind === 'area'
      ? entryKeys.areaCase(holder.key, params)
      : entryKeys.projectCase(holder.key, params);
  return infiniteQueryOptions({
    queryKey,
    queryFn: ({ pageParam }): Promise<Page<Entry>> =>
      holder.kind === 'area'
        ? readAreaCasePage(holder.key, params, pageParam)
        : readProjectCasePage(holder.key, params, pageParam),
    initialPageParam: '',
    getNextPageParam: nextCursor,
  });
}

/**
 * Лента дела страницами по курсору бэкенда: дело целиком не читается никогда — оно
 * растёт, и «показать всё» однажды перестанет помещаться в ответ.
 */
export function caseFeedQueryOptions(taskKey: string, params: EntryListParams) {
  return infiniteQueryOptions({
    queryKey: entryKeys.feed(taskKey, params),
    queryFn: ({ pageParam }): Promise<Page<Entry>> =>
      unwrapPage(
        apiClient.GET('/api/v1/tasks/{task_key}/entries', {
          params: {
            path: { task_key: taskKey },
            query: {
              limit: ENTRY_PAGE_SIZE,
              ...params,
              cursor: pageParam === '' ? undefined : pageParam,
            },
          },
        }),
      ),
    initialPageParam: '',
    getNextPageParam: (last: Page<Entry>) =>
      last.meta?.has_more === true ? (last.meta.next_cursor ?? undefined) : undefined,
    placeholderData: keepPreviousData,
  });
}

/** Предел страниц знания области: 25 страниц по 200 записей — потолок, а не ожидаемый размер. */
const KNOWLEDGE_MAX_PAGES = 25;

/** Типы записей, из которых состоит знание области: решения и заметки (TRK#57, §5). */
export const KNOWLEDGE_TYPES: EntryType[] = ['decision', 'finding', 'note'];

/**
 * Знание области — все её решения и заметки, действующие и заменённые, по номеру
 * (TRK-660, TRK#59). Читается целиком, страница за страницей: экрану нужны числа вкладок
 * и переключатель «Показать заменённые», а для них пришлось бы знать все записи; дело
 * области коротко (решения и заметки, без сводок и вопросов задач).
 *
 * `text` — поиск бэкенда по названию и телу записи. Пустая строка уходит без параметра.
 * Ключ лежит под префиксом области: действие в деле области перечитывает и его.
 */
export function areaKnowledgeQueryOptions(address: string, text: string) {
  return queryOptions({
    queryKey: entryKeys.areaKnowledge(address, text),
    // Набор слова в поиске не гасит список между запросами.
    placeholderData: keepPreviousData,
    queryFn: async (): Promise<Entry[]> => {
      const items: Entry[] = [];
      let cursor = '';
      for (let page = 0; page < KNOWLEDGE_MAX_PAGES; page += 1) {
        const read = await readAreaCasePage(
          address,
          { types: KNOWLEDGE_TYPES, ...(text === '' ? {} : { text }) },
          cursor,
        );
        items.push(...read.items);
        const next = nextCursor(read);
        if (next === undefined) break;
        cursor = next;
      }
      return items;
    },
  });
}

/** Страниц решений и находок одного дела задачи не больше: потолок, а не ожидаемый размер. */
const DRAFT_MAX_PAGES = 25;

/**
 * Решения и находки дела задачи с нагрузкой и `lifted_by` — всё, из чего интерфейс
 * находит черновики знания (TRK-661). Опись дела заголовками адреса подъёма не несёт, а
 * «поднят ли» посчитан только в чтении записей, поэтому читаются тела этих двух типов,
 * страница за страницей. Черновики выбираются на стороне экрана (`draftOfEntry`): сам
 * признак подъёма бэкенд отдаёт готовым.
 *
 * Ключ лежит под префиксом задачи: подъём — запись в деле адресата, и живая лента
 * перечитывает задачу целиком.
 */
export function taskDraftsQueryOptions(taskKey: string, enabled: boolean) {
  return queryOptions({
    queryKey: entryKeys.drafts(taskKey),
    enabled,
    queryFn: async (): Promise<Entry[]> => {
      const items: Entry[] = [];
      let cursor = '';
      for (let page = 0; page < DRAFT_MAX_PAGES; page += 1) {
        const read = await unwrapPage(
          apiClient.GET('/api/v1/tasks/{task_key}/entries', {
            params: {
              path: { task_key: taskKey },
              query: {
                limit: PROJECT_ENTRY_PAGE_SIZE,
                types: ['decision', 'finding'],
                cursor: cursor === '' ? undefined : cursor,
              },
            },
          }),
        );
        items.push(...read.items);
        const next = nextCursor(read);
        if (next === undefined) break;
        cursor = next;
      }
      return items;
    },
  });
}
