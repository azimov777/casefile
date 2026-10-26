import type { FileFilter, FileSort } from '@/entities/file';

/**
 * Виды файлов, по которым отбирают («все документы Word»): ключ в адресе и тип, который
 * ждёт сервер. `image` — семейство, остальное — точный тип; список конечный и не
 * претендует на полноту: нужный тип сервер отберёт и по любой строке `mime_type`.
 */
export const TYPE_PRESETS = {
  image: 'image',
  pdf: 'application/pdf',
  word: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  excel: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  text: 'text',
  audio: 'audio',
  video: 'video',
} as const;

export type TypePreset = keyof typeof TYPE_PRESETS;

export const TYPE_KEYS = Object.keys(TYPE_PRESETS) as TypePreset[];

export const SORT_KEYS: FileSort[] = ['added', 'opened', 'size', 'type'];

function isPreset(value: string | null): value is TypePreset {
  return value !== null && Object.prototype.hasOwnProperty.call(TYPE_PRESETS, value);
}

function isSort(value: string | null): value is FileSort {
  return SORT_KEYS.some((key) => key === value);
}

/** Отбор из адреса страницы: `q`, `project`, `type`, `sort`, `order=asc`. Лишнее и неизвестное отбрасывается. */
export function readFileFilter(params: URLSearchParams): FileFilter {
  const type = params.get('type');
  const sort = params.get('sort');
  const project = params.get('project');
  return {
    q: params.get('q') ?? '',
    project: project === null || project === '' ? null : project,
    mimeType: isPreset(type) ? TYPE_PRESETS[type] : null,
    sort: isSort(sort) ? sort : 'added',
    descending: params.get('order') !== 'asc',
    unopened: false,
  };
}

/** Ключ вида файлов в адресе по типу отбора; `null`, если тип не из списка. */
export function typePresetOf(filter: FileFilter): TypePreset | null {
  const found = TYPE_KEYS.find((key) => TYPE_PRESETS[key] === filter.mimeType);
  return found ?? null;
}

/** Сколько условий отбора включено: поиск, проект, тип. Порядок отбором не считается. */
export function activeConditions(filter: FileFilter): number {
  return (
    (filter.q !== '' ? 1 : 0) +
    (filter.project !== null ? 1 : 0) +
    (filter.mimeType !== null ? 1 : 0)
  );
}

/** Новый адрес после правки условия: умолчания в адрес не пишутся, у одного вида один адрес. */
export function withFilter(
  params: URLSearchParams,
  change: Partial<{
    q: string;
    project: string | null;
    type: TypePreset | null;
    sort: FileSort;
    descending: boolean;
  }>,
): URLSearchParams {
  const next = new URLSearchParams(params);
  const set = (key: string, value: string | null) => {
    if (value === null || value === '') next.delete(key);
    else next.set(key, value);
  };
  if ('q' in change) set('q', change.q ?? '');
  if ('project' in change) set('project', change.project ?? null);
  if ('type' in change) set('type', change.type ?? null);
  if ('sort' in change) set('sort', change.sort === 'added' ? null : (change.sort ?? null));
  if ('descending' in change) set('order', change.descending === false ? 'asc' : null);
  return next;
}
