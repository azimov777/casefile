import { Link } from 'react-router';
import { Badge } from '@/shared/ui';
import { taskRefHref } from '@/shared/lib/task-refs';
import type { LiveJournal } from '../model/use-live-journal';
import styles from './question-notice.module.css';

/**
 * Вопросы, адресованные этому человеку и пришедшие при открытом приложении.
 *
 * Ответ на вопрос — единственное, ради чего человек в трекере что-то делает
 * (`CONCEPT.md`, 1), поэтому это единственное событие, которому позволено привлекать
 * внимание движением. Оно же единственное, что не должно двигать чужое: место у стопки
 * своё, вне потока вёрстки, — появление уведомления не смещает ни шапку, ни таблицу.
 *
 * Уведомление живёт, пока человек его не закрыл или не перешёл по нему. По таймеру
 * не гаснет намеренно: пропущенное уведомление хуже отсутствующего — человек, который
 * отвернулся на минуту, не узнал бы, что его спрашивали.
 */
export function QuestionNotice({
  incomingQuestions,
  dismissQuestion,
}: Pick<LiveJournal, 'incomingQuestions' | 'dismissQuestion'>) {
  return (
    // Стопка существует всегда, даже пустая, и `aria-live` стоит на ней, а не на
    // карточке: экранный диктор объявляет изменения внутри области, которую он уже
    // наблюдает. Область, появившаяся вместе со своим текстом, не объявляется вовсе —
    // объявлять было нечего в тот момент, когда её начали наблюдать.
    //
    // Пустая стопка ничего не занимает: она вне потока вёрстки и без содержимого
    // не имеет размеров.
    <aside className={styles.stack} aria-label="Вопросы ко мне" aria-live="polite">
      {incomingQuestions.map((question) => (
        <article className={styles.notice} key={question.id}>
          <p className={styles.head}>
            <Link
              className={styles.key}
              to={taskRefHref({ key: question.taskKey, entryNo: question.no })}
              onClick={() => dismissQuestion(question.id)}
            >
              {question.taskKey}#{question.no}
            </Link>
            {question.blocking ? (
              <Badge tone="danger" title="Работа по задаче стоит без ответа">
                блокирующий
              </Badge>
            ) : null}
          </p>

          <p className={styles.title}>{question.title}</p>

          <button
            className={styles.dismiss}
            type="button"
            onClick={() => dismissQuestion(question.id)}
            aria-label={`Закрыть уведомление о вопросе ${question.taskKey}#${question.no}`}
          >
            ×
          </button>
        </article>
      ))}
    </aside>
  );
}
