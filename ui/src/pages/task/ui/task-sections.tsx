import type { TaskDetails } from '@/entities/task';
import { Markdown } from '@/shared/ui';

/**
 * Надстрочная подпись раздела: заглавными, с разрядкой — без неё буквы слипаются.
 *
 * Разрядка своя, а не `tracking-caps` (0.06em): у подписей раздела она 0.04em, и
 * подмена токеном раздвинула бы каждую подпись задания. Перевод оформления вида
 * не меняет, а свести две разрядки в одну — это решение о наборе, и заводится оно
 * своей задачей.
 */
const SECTION_TITLE = 'text-meta font-bold tracking-[0.04em] text-muted uppercase';

/**
 * Пять разделов задачи и обзорные проверки.
 *
 * Проверки — нумерованный список с единицы: номер это позиция в `checks`, и по нему
 * вердикт называет проверку (`check_no`). Своей нумерации у списка быть не может.
 */
export function TaskSections({ task }: { task: TaskDetails }) {
  return (
    <div className="flex flex-col gap-4">
      <Section title="Описание" value={task.description} />
      <Section title="Цель" value={task.goal} />
      <Section title="Контекст" value={task.context} />
      <Section title="Ограничения" value={task.constraints} />
      <Section title="Выход" value={task.output} />

      <section className="flex flex-col gap-2">
        <h3 className={SECTION_TITLE}>Обзорные проверки</h3>
        {task.checks.length === 0 ? (
          <p className="text-muted italic">Проверок нет.</p>
        ) : (
          /* Отступ слева — место под номера: маркер нумерованного списка стоит
             снаружи строки, и без него номера ушли бы за край блока. */
          <ol className="flex flex-col gap-1 pl-6">
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
    <section className="flex flex-col gap-2">
      <h3 className={SECTION_TITLE}>{title}</h3>
      {value.trim() === '' ? (
        <p className="text-muted italic">Раздел пуст.</p>
      ) : (
        <Markdown>{value}</Markdown>
      )}
    </section>
  );
}
