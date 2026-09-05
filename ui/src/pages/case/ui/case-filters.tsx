import { ENTRY_TYPES, isServiceEntry, type EntryType } from '@/entities/entry';
import { Button } from '@/shared/ui';
import styles from './case-filters.module.css';

interface CaseFiltersProps {
  selected: EntryType[];
  onChange: (types: EntryType[]) => void;
}

/**
 * Отбор по типам записей: две группы и отдельные типы.
 *
 * Перечня типов здесь нет: он приходит из `ENTRY_TYPES`, собранного из перечисления
 * контракта, а «служебный ли тип» решает `isServiceEntry` — та же причина, по которой
 * доска не знает списка статусов.
 */
export function CaseFilters({ selected, onChange }: CaseFiltersProps) {
  const agentTypes = ENTRY_TYPES.filter((type) => !isServiceEntry(type));
  const serviceTypes = ENTRY_TYPES.filter(isServiceEntry);

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
      <div className={styles.groups}>
        <Button tone="quiet" onClick={() => onChange([])} disabled={selected.length === 0}>
          Все записи
        </Button>
        <Button tone="quiet" onClick={() => chooseGroup(agentTypes)}>
          Записи агента
        </Button>
        <Button tone="quiet" onClick={() => chooseGroup(serviceTypes)}>
          Служебные
        </Button>
      </div>

      <fieldset className={styles.types}>
        <legend className={styles.legend}>Типы</legend>
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
    </section>
  );
}
