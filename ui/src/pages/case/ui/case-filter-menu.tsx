import { useId } from 'react';
import { useTranslation } from 'react-i18next';
import { Square, SquareCheck } from 'lucide-react';
import { ENTRY_TYPES, EntryTypeIcon, isServiceEntry, type EntryType } from '@/entities/entry';
import { ToggleGroup, ToggleGroupItem } from '@/shared/ui';

/** Типы записей агента и служебные типы трекера — те же два деления, что были у флажков. */
const AGENT_TYPES = ENTRY_TYPES.filter((type) => !isServiceEntry(type));
const SERVICE_TYPES = ENTRY_TYPES.filter(isServiceEntry);

interface CaseFilterMenuProps {
  selected: EntryType[];
  onChange: (types: EntryType[]) => void;
}

/**
 * Панель «Фильтр» отбора записей дела: тип отбирается одним нажатием, панель не
 * закрывается — восемнадцать типов ставятся подряд, а не по одному открытию (UI-137).
 *
 * Групп две, как раньше у флажков (`filters.agentEntries`/`filters.serviceEntries`), и
 * подпись каждой — тоже кнопка: нажатие ставит или снимает свою группу целиком, не трогая
 * другую (`TypeGroup` ниже — не общий `shared/ui` `FilterGroup`, потому что его подпись
 * не кнопка, а простой текст: у отбора задач группы маленькие, и ставить их целиком
 * незачем). Против прежнего `chooseGroup` (до UI-137, «Записи агента» / «Служебные»
 * заменяли весь отбор целиком) это чинит зависимость групп: там второе нажатие стирало
 * первое, а не складывалось с ним.
 */
export function CaseFilterMenu({ selected, onChange }: CaseFilterMenuProps) {
  const { t } = useTranslation('case');

  /** Ставит или снимает группу целиком, не трогая отбор другой группы. */
  function toggleGroup(group: EntryType[]) {
    const allOn = group.every((type) => selected.includes(type));
    const withoutGroup = selected.filter((type) => !group.includes(type));
    onChange(allOn ? withoutGroup : [...withoutGroup, ...group]);
  }

  /** Переключатели своей группы — новый набор внутри неё, отбор другой группы цел. */
  function applyGroup(group: EntryType[], next: EntryType[]) {
    const withoutGroup = selected.filter((type) => !group.includes(type));
    onChange([...withoutGroup, ...next]);
  }

  return (
    <div className="flex flex-col gap-3">
      <TypeGroup
        label={t('filters.agentEntries')}
        types={AGENT_TYPES}
        selected={selected}
        onToggleGroup={() => toggleGroup(AGENT_TYPES)}
        onChange={(next) => applyGroup(AGENT_TYPES, next)}
      />
      <TypeGroup
        label={t('filters.serviceEntries')}
        types={SERVICE_TYPES}
        selected={selected}
        onToggleGroup={() => toggleGroup(SERVICE_TYPES)}
        onChange={(next) => applyGroup(SERVICE_TYPES, next)}
      />
    </div>
  );
}

/**
 * Одна группа панели: подпись-кнопка (снимает или ставит группу целиком) и переключатели
 * её типов, знаком те же, что и в описи и в ленте (`EntryTypeIcon`).
 */
function TypeGroup({
  label,
  types,
  selected,
  onToggleGroup,
  onChange,
}: {
  label: string;
  types: EntryType[];
  selected: EntryType[];
  onToggleGroup: () => void;
  onChange: (next: EntryType[]) => void;
}) {
  const labelId = useId();
  const allOn = types.every((type) => selected.includes(type));

  return (
    <div className="flex flex-col gap-1.5">
      {/*
       * Заголовок-переключатель, а не приглушённая ссылка (была до правки владельца,
       * UI-137#11: «выглядят как-то серо» — пунктирное подчёркивание муторного цвета
       * рядом с яркими пилюлями типов читалось вторым сортом). Знак впереди называет
       * состояние глазами, `aria-pressed` — диктору; тот же `id`, что называет группу
       * переключателям ниже (`aria-labelledby`), чтобы она не читалась дважды одним
       * словом.
       *
       * Фон и рамка названы явно (`border-none bg-transparent`): без них браузер рисует
       * свою заливку `ButtonFace` (в тёмной теме Chromium — `#6b6b6b`) поверх фона
       * панели — тот самый серый прямоугольник со снимка. Поймано `axe` в
       * `e2e/task.spec.ts`, «доступность ленты дела» (`docs/notes/ui.md`, «Кнопка без
       * объявленного фона получает `ButtonFace` браузера»).
       */}
      <button
        id={labelId}
        type="button"
        aria-pressed={allOn}
        className="inline-flex w-fit items-center gap-1.5 rounded-mark border-none bg-transparent p-0 text-label font-semibold text-text transition-colors duration-(--motion-fast) ease-fast hover:text-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
        onClick={onToggleGroup}
      >
        {allOn ? (
          <SquareCheck className="size-(--ui-mark) shrink-0 text-accent" aria-hidden="true" />
        ) : (
          <Square className="size-(--ui-mark) shrink-0 text-muted" aria-hidden="true" />
        )}
        {label}
      </button>
      <ToggleGroup
        aria-labelledby={labelId}
        value={selected.filter((type) => types.includes(type))}
        onValueChange={(value) => onChange(value as EntryType[])}
      >
        {types.map((type) => (
          <ToggleGroupItem key={type} value={type}>
            <EntryTypeIcon type={type} />
            <code>{type}</code>
          </ToggleGroupItem>
        ))}
      </ToggleGroup>
    </div>
  );
}
