import type { TaskDetails } from '@/entities/task';
import { Markdown } from '@/shared/ui';
import styles from './task-sections.module.css';

/**
 * Пять разделов задачи и обзорные проверки.
 *
 * Проверки — нумерованный список с единицы: номер это позиция в `checks`, и по нему
 * вердикт называет проверку (`check_no`). Своей нумерации у списка быть не может.
 */
export function TaskSections({ task }: { task: TaskDetails }) {
  return (
    <div className={styles.sections}>
      <Section title="Описание" value={task.description} />
      <Section title="Цель" value={task.goal} />
      <Section title="Контекст" value={task.context} />
      <Section title="Ограничения" value={task.constraints} />
      <Section title="Выход" value={task.output} />

      <section className={styles.section}>
        <h3 className={styles.title}>Обзорные проверки</h3>
        {task.checks.length === 0 ? (
          <p className={styles.empty}>Проверок нет.</p>
        ) : (
          <ol className={styles.checks}>
            {task.checks.map((check, index) => (
              <li key={index}>
                <Markdown>{check}</Markdown>
              </li>
            ))}
          </ol>
        )}
      </section>
    </div>
  );
}

function Section({ title, value }: { title: string; value: string }) {
  return (
    <section className={styles.section}>
      <h3 className={styles.title}>{title}</h3>
      {value.trim() === '' ? (
        <p className={styles.empty}>Раздел пуст.</p>
      ) : (
        <Markdown>{value}</Markdown>
      )}
    </section>
  );
}
