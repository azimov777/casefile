import { useId, useRef, useState } from 'react';
import { X } from 'lucide-react';
import { ENTRY_TYPES, isServiceEntry, type EntryType } from '@/entities/entry';
import { Button } from '@/shared/ui';
import styles from './case-filters.module.css';

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
    <section className={styles.panel} aria-label="Отбор записей">
      <div className={styles.bar}>
        <Button
          ref={toggleRef}
          tone="quiet"
          aria-expanded={expanded}
          aria-controls={typesId}
          onClick={() => setExpanded(!expanded)}
        >
          {expanded ? 'Свернуть типы' : 'Выбрать типы'}
        </Button>

        <div className={styles.groups}>
          <Button tone="quiet" onClick={() => chooseGroup(agentTypes)}>
            Записи агента
          </Button>
          <Button tone="quiet" onClick={() => chooseGroup(serviceTypes)}>
            Служебные
          </Button>
        </div>

        {/* Список, а не абзац: программа чтения с экрана называет число отобранных
            типов вслух, а `aria-label` роль абзаца не принимает. */}
        <ul className={styles.conditions} aria-label="Отобранные типы записей">
          {chosen.length === 0 ? (
            <li className={styles.all}>показаны все записи</li>
          ) : (
            chosen.map((type) => (
              <li key={type} className={styles.chip}>
                <code>{type}</code>
                <button
                  type="button"
                  className={styles.remove}
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
        <fieldset id={typesId} className={styles.types}>
          <legend className={styles.legend}>Типы записей</legend>
          {ENTRY_TYPES.map((type) => (
            <label key={type} className={styles.check}>
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
