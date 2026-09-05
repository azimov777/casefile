import type { TaskView } from '@/features/task-filters';
import styles from './view-switch.module.css';

interface ViewSwitchProps {
  view: TaskView;
  onChange: (view: TaskView) => void;
}

const VIEWS: { value: TaskView; label: string }[] = [
  { value: 'table', label: 'Таблица' },
  { value: 'board', label: 'Доска' },
];

/**
 * Переключатель режима. Радиогруппа, а не две кнопки: выбран всегда ровно один режим,
 * и программа чтения с экрана должна это сказать — из пары кнопок она не поймёт,
 * которая сейчас действует.
 */
export function ViewSwitch({ view, onChange }: ViewSwitchProps) {
  return (
    <fieldset className={styles.switch}>
      <legend className={styles.legend}>Показывать</legend>
      {VIEWS.map((option) => (
        <label key={option.value} className={styles.option}>
          <input
            type="radio"
            name="view"
            value={option.value}
            checked={view === option.value}
            onChange={() => onChange(option.value)}
          />
          {option.label}
        </label>
      ))}
    </fieldset>
  );
}
