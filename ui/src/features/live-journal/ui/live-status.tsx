import { Link } from 'react-router';
import type { LiveJournal } from '../model/use-live-journal';
import styles from './live-status.module.css';

/**
 * Состояние живого потока и новый вопрос — рядом, в шапке: оба говорят «то, на что вы
 * смотрите, только что изменилось» (`CONCEPT.md`, 5).
 */
export function LiveStatus({ status, incomingQuestion, dismissQuestion }: LiveJournal) {
  return (
    <span className={styles.live}>
      {incomingQuestion === null ? null : (
        <Link
          className={styles.question}
          to={`/tasks/${incomingQuestion.taskKey}?entry=${incomingQuestion.no}`}
          onClick={dismissQuestion}
        >
          Вам вопрос: {incomingQuestion.taskKey}#{incomingQuestion.no}
        </Link>
      )}

      <span
        className={status === 'live' ? styles.connected : styles.lost}
        role="status"
        title={
          status === 'live'
            ? 'Живой поток журнала открыт: экран обновляется сам'
            : 'Соединение с потоком журнала потеряно, идёт переподключение'
        }
      >
        {status === 'live' ? 'на связи' : 'нет связи'}
      </span>
    </span>
  );
}
