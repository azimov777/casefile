import { useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ListFilter } from 'lucide-react';
import { ENTRY_TYPES, type EntryType } from '@/entities/entry';
import {
  Button,
  FilterChip,
  FilterChipList,
  FilterCountBadge,
  FilterResetButton,
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/shared/ui';
import { CaseFilterMenu } from './case-filter-menu';

interface CaseFiltersProps {
  selected: EntryType[];
  onChange: (types: EntryType[]) => void;
}

/**
 * Отбор по типам записей: строка инструментов с кнопкой «Фильтр» и строка состояния
 * с чипами отобранного — тот же вид, что у отбора задач (UI-130, UI-137). До этой задачи
 * здесь стояла кнопка «Выбрать типы» и восемнадцать системных флажков под ней в
 * раскрывающемся в потоке вёрстки месте: два экрана с одним смыслом обязаны выглядеть
 * одинаково, а не расходиться каждый своей формой.
 *
 * Условия одни — типы записи, — поэтому в отличие от отбора задач здесь нет ни поиска,
 * ни сортировки, ни режима запроса: только кнопка «Фильтр» и то, что ею отобрано.
 */
export function CaseFilters({ selected, onChange }: CaseFiltersProps) {
  const [open, setOpen] = useState(false);
  /*
   * Кнопка «Фильтр» — якорь фокуса: снятый чип исчезает вместе со своей кнопкой, и фокус
   * улетел бы на `body`. Тот же приём, что в отборе задач.
   */
  const menuRef = useRef<HTMLButtonElement>(null);
  const { t } = useTranslation('case');

  /*
   * Порядок чипов — порядок контракта, а не порядок нажатий: иначе один и тот же
   * отбор, собранный в разной последовательности, читался бы двумя разными строками.
   */
  const chosen = ENTRY_TYPES.filter((type) => selected.includes(type));

  function remove(type: EntryType) {
    onChange(selected.filter((item) => item !== type));
  }

  return (
    <section className="flex flex-col gap-2" aria-label={t('filters.label')}>
      {/* Строка инструментов: чем отбирать. */}
      <div className="flex flex-wrap items-center gap-2">
        <Popover open={open} onOpenChange={setOpen}>
          <PopoverTrigger asChild>
            <Button ref={menuRef} tone="quiet" size="sm">
              <ListFilter className="size-(--ui-mark)" aria-hidden="true" />
              {t('filters.menu')}
              {chosen.length === 0 ? null : <FilterCountBadge count={chosen.length} />}
            </Button>
          </PopoverTrigger>
          <PopoverContent className="w-96" aria-label={t('filters.menuLabel')}>
            <CaseFilterMenu selected={selected} onChange={onChange} />
          </PopoverContent>
        </Popover>
      </div>

      {/* Строка состояния: что отобрано сейчас. */}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <FilterChipList label={t('filters.chosen')}>
          {chosen.length === 0 ? (
            <li className="text-meta text-muted">{t('filters.allShown')}</li>
          ) : (
            chosen.map((type) => (
              <FilterChip
                key={type}
                label={<code>{type}</code>}
                removeLabel={t('filters.remove', { type })}
                onOpen={() => setOpen(true)}
                onRemove={() => {
                  remove(type);
                  menuRef.current?.focus();
                }}
              />
            ))
          )}
        </FilterChipList>

        {chosen.length === 0 ? null : (
          <FilterResetButton onClick={() => onChange([])}>{t('filters.reset')}</FilterResetButton>
        )}
      </div>
    </section>
  );
}
