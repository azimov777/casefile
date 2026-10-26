import { useEffect, useId, useState } from 'react';
import { ArrowDownUp, Search } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import type { FileFilter, FileSort } from '@/entities/file';
import { Button, Input, Select } from '@/shared/ui';
import {
  SORT_KEYS,
  TYPE_KEYS,
  activeConditions,
  typePresetOf,
  type TypePreset,
} from '../model/file-filters';

/** Значение «без условия» в выпадающих списках: у Radix пустой строки среди значений нет. */
const ANY = 'any';

/** Пауза между набором и запросом: пока человек печатает, список не перечитывается на каждую букву. */
const TYPING_PAUSE_MS = 250;

export interface FileFilterChange {
  q?: string;
  project?: string | null;
  type?: TypePreset | null;
  sort?: FileSort;
  descending?: boolean;
}

/**
 * Поиск по имени, отбор по проекту и типу, порядок и направление. Ничего не хранит
 * сам: отбор живёт в адресе страницы (TRK/ui-api#4), сюда он приходит готовым, а правка
 * уходит наверх. Поле поиска держит набираемую строку у себя и отдаёт её паузой.
 */
export function FilesToolbar({
  filter,
  projects,
  onChange,
  onReset,
}: {
  filter: FileFilter;
  projects: { key: string; title: string }[];
  onChange: (change: FileFilterChange) => void;
  onReset: () => void;
}) {
  const { t } = useTranslation('files');
  const searchId = useId();
  const [draft, setDraft] = useState(filter.q);
  const [lastQ, setLastQ] = useState(filter.q);
  const conditions = activeConditions(filter);

  // Адрес изменили снаружи (сброс, «назад»): набранное заменяется адресным.
  if (filter.q !== lastQ) {
    setLastQ(filter.q);
    setDraft(filter.q);
  }

  useEffect(() => {
    if (draft === filter.q) return;
    const timer = setTimeout(() => onChange({ q: draft }), TYPING_PAUSE_MS);
    return () => clearTimeout(timer);
  }, [draft, filter.q, onChange]);

  return (
    /*
     * Не `<form>`: Radix Select внутри формы держит скрытый родной `<select>` без пунктов
     * (они в закрытом списке не смонтированы) и на каждой смене значения отвечает событием
     * `change` с пустой строкой — отбор сбрасывался бы сам. Роль `search` даёт ту же
     * область для чтения с экрана, Enter в поле поиска применяет набранное сразу.
     */
    <div
      role="search"
      aria-label={t('filters.label')}
      className="flex min-w-0 flex-wrap items-end gap-x-4 gap-y-3"
    >
      <div className="flex min-w-0 flex-1 basis-56 flex-col gap-1">
        <label className="text-meta text-muted" htmlFor={searchId}>
          {t('filters.search')}
        </label>
        <div className="relative">
          <Search
            className="pointer-events-none absolute top-1/2 left-3 size-(--ui-mark) -translate-y-1/2 text-faint"
            aria-hidden="true"
          />
          <Input
            id={searchId}
            type="search"
            className="pl-9"
            value={draft}
            placeholder={t('filters.searchPlaceholder')}
            autoComplete="off"
            spellCheck={false}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') onChange({ q: draft });
            }}
          />
        </div>
      </div>

      <div className="flex min-w-0 flex-wrap items-center gap-2">
        <Select
          label={t('filters.project')}
          value={filter.project ?? ANY}
          onValueChange={(value) => onChange({ project: value === ANY ? null : value })}
          options={[
            { value: ANY, label: t('filters.allProjects') },
            ...projects.map((project) => ({
              value: project.key,
              label: `${project.key} — ${project.title}`,
            })),
          ]}
          className="border-line-strong"
        />
        <Select
          label={t('filters.type')}
          value={typePresetOf(filter) ?? ANY}
          onValueChange={(value) =>
            onChange({ type: TYPE_KEYS.find((key) => key === value) ?? null })
          }
          options={[
            { value: ANY, label: t('filters.types.all') },
            ...TYPE_KEYS.map((key) => ({ value: key, label: t(`filters.types.${key}`) })),
          ]}
          className="border-line-strong"
        />
      </div>

      <div className="flex min-w-0 flex-wrap items-center gap-2">
        <Select
          label={t('filters.sort')}
          value={filter.sort}
          onValueChange={(value) => {
            const next = SORT_KEYS.find((key) => key === value);
            if (next !== undefined) onChange({ sort: next });
          }}
          options={SORT_KEYS.map((key) => ({ value: key, label: t(`filters.sorts.${key}`) }))}
          icon={<ArrowDownUp className="size-(--ui-mark) text-faint" aria-hidden="true" />}
          className="border-line-strong"
        />
        <Button
          tone="quiet"
          size="sm"
          aria-label={t('filters.direction', {
            current: filter.descending ? t('filters.descending') : t('filters.ascending'),
          })}
          onClick={() => onChange({ descending: !filter.descending })}
        >
          {filter.descending ? t('filters.descending') : t('filters.ascending')}
        </Button>
        {conditions === 0 ? null : (
          <Button tone="quiet" size="sm" onClick={onReset}>
            {t('filters.reset')}
          </Button>
        )}
      </div>
    </div>
  );
}
