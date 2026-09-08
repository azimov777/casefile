import { useId, useRef, useState } from 'react';
import { X } from 'lucide-react';
import { ENTRY_TYPES, isServiceEntry, type EntryType } from '@/entities/entry';
import { Button } from '@/shared/ui';

interface CaseFiltersProps {
  selected: EntryType[];
  onChange: (types: EntryType[]) => void;
}

/**
 * Отбор по типам записей: строка с тем, что отобрано, и восемнадцать флажков под ней.
 *
 * Перечня типов здесь нет: он приходит из `ENTRY_TYPES`, собранного из перечисления
 * контракта, а «служебный ли тип» решает `isServiceEntry` — та же причина, по которой
 * доска не знает списка статусов.
 *
 * Флажки свёрнуты по умолчанию (UI-26). Развёрнутыми они занимали около 150 px до
 * первой записи дела — а дело человек открывает читать, а не отбирать. Свёрнут при
 * этом только *перечень типов*: выбранные типы названы поимённо чипами, и ни одного
 * не спрятано за счётчиком — список, часть условий которого не видна, принимают
 * за полное дело.
 */
export function CaseFilters({ selected, onChange }: CaseFiltersProps) {
  const [expanded, setExpanded] = useState(false);
  const typesId = useId();
  /*
   * Кнопка раскрытия — якорь фокуса: снятый чип исчезает вместе со своей кнопкой,
   * и фокус улетел бы на `body`. Тот же приём, что в отборе задач.
   */
  const toggleRef = useRef<HTMLButtonElement>(null);

  const agentTypes = ENTRY_TYPES.filter((type) => !isServiceEntry(type));
  const serviceTypes = ENTRY_TYPES.filter(isServiceEntry);

  /*
   * Порядок чипов — порядок контракта, а не порядок нажатий: иначе один и тот же
   * отбор, собранный в разной последовательности, читался бы двумя разными строками.
   */
  const chosen = ENTRY_TYPES.filter((type) => selected.includes(type));

  function toggle(type: EntryType, on: boolean) {
    onChange(on ? [...selected, type] : selected.filter((item) => item !== type));
  }

  /** Группа целиком: включена, когда выбраны все её типы. */
  function chooseGroup(group: EntryType[]) {
    const all = group.every((type) => selected.includes(type));
    onChange(all ? [] : group);
  }

  return (
    <section className="flex flex-col gap-2" aria-label="Отбор записей">
      {/*
       * Свёрнутый вид: одна строка, которая называет весь отбор. Её высота и есть то,
       * что дело платит за отбор, — всё остальное принадлежит записям. Тот же язык, что
       * у строки отбора списка задач: два экрана с одним смыслом обязаны выглядеть
       * одинаково.
       */}
      <div className="flex flex-wrap items-center gap-2 rounded-control border border-line bg-surface px-3 py-2">
        <Button
          ref={toggleRef}
          tone="quiet"
          aria-expanded={expanded}
          aria-controls={typesId}
          onClick={() => setExpanded(!expanded)}
        >
          {expanded ? 'Свернуть типы' : 'Выбрать типы'}
        </Button>

        <div className="flex flex-wrap gap-2">
          <Button tone="quiet" onClick={() => chooseGroup(agentTypes)}>
            Записи агента
          </Button>
          <Button tone="quiet" onClick={() => chooseGroup(serviceTypes)}>
            Служебные
          </Button>
        </div>

        {/* Список, а не абзац: программа чтения с экрана называет число отобранных
            типов вслух, а `aria-label` роль абзаца не принимает.

            Отобранные типы занимают свободное место (`flex-[1_1_12rem]`) и переносятся
            на вторую строку, когда их много. Ни `overflow: hidden`, ни счётчика
            «ещё 5»: спрятанное условие — это отфильтрованное дело, которое принимают
            за полное. */}
        <ul
          className="flex flex-[1_1_12rem] flex-wrap items-center gap-x-2 gap-y-1 list-none p-0"
          aria-label="Отобранные типы записей"
        >
          {chosen.length === 0 ? (
            <li className="text-meta text-muted">показаны все записи</li>
          ) : (
            chosen.map((type) => (
              // Чип типа: имя из контракта моноширинным, кнопка рядом снимает его
              // с отбора. Строка не переносится — имя типа читают целиком.
              <li
                key={type}
                className="inline-flex items-center gap-1 rounded-pill border border-line-strong bg-surface pr-1 pl-2 text-mark leading-[1.7] whitespace-nowrap text-text"
              >
                <code>{type}</code>
                <button
                  type="button"
                  /*
                   * Переход назван свойством, а не `transition-colors`: движется
                   * только заливка, цвет знака меняется сразу — так это и было
                   * написано в модуле. Фон назван явно: у `<button>` без
                   * объявленного фона браузер рисует свой `ButtonFace`
                   * (`docs/notes/ui.md`).
                   */
                  className="grid place-items-center rounded-pill border-none bg-transparent p-0 leading-none text-muted transition-[background-color] duration-(--motion-fast) ease-fast hover:bg-sunken hover:text-text"
                  aria-label={`Убрать тип: ${type}`}
                  onClick={() => {
                    toggle(type, false);
                    toggleRef.current?.focus();
                  }}
                >
                  <X className="size-(--ui-mark)" aria-hidden="true" />
                </button>
              </li>
            ))
          )}
        </ul>

        {chosen.length === 0 ? null : (
          <Button tone="quiet" onClick={() => onChange([])}>
            Все записи
          </Button>
        )}
      </div>

      {expanded ? (
        <fieldset
          id={typesId}
          className="flex flex-wrap gap-x-3 gap-y-2 rounded-control border border-line bg-surface px-4 py-3"
        >
          <legend className="text-meta text-muted">Типы записей</legend>
          {ENTRY_TYPES.map((type) => (
            <label key={type} className="inline-flex cursor-pointer items-center gap-1 text-meta">
              <input
                type="checkbox"
                checked={selected.includes(type)}
                onChange={(event) => toggle(type, event.target.checked)}
              />
              <code>{type}</code>
            </label>
          ))}
        </fieldset>
      ) : null}
    </section>
  );
}
