import { Link } from 'react-router';
import { Markdown } from '@/shared/ui';
import { taskRefHref } from '@/shared/lib/task-refs';
import type { Answered } from '../model/answering';
import styles from './answer-receipt.module.css';

interface AnswerReceiptProps {
  taskKey: string;
  questionNo: number;
  answered: Answered;
  onClose: () => void;
}

/**
 * Подтверждение: ответ подшит, вот его номер и вот что в нём написано.
 *
 * Стоит на месте формы, под тем же вопросом, а не на новом экране: человек видит,
 * на что он ответил и чем, одним взглядом. Раньше здесь не было ничего — блок
 * «Открытые вопросы» вместе с вопросом и формой просто исчезал, и единственным
 * признаком, что что-то произошло, был счётчик в шапке.
 *
 * Не гаснет по таймеру: подтверждение, которое человек не успел прочитать, ничем
 * не лучше отсутствующего.
 */
export function AnswerReceipt({ taskKey, questionNo, answered, onClose }: AnswerReceiptProps) {
  return (
    <section className={styles.receipt} aria-label={`Ответ на ${taskKey}#${questionNo} подшит`}>
      <p className={styles.head}>
        <span className={styles.done}>Ответ подшит</span>
        {/* Номер записи — из ответа сервера: по этой ссылке ответ действительно лежит. */}
        <Link
          className={styles.entry}
          to={taskRefHref({ key: taskKey, entryNo: answered.entryNo })}
        >
          {taskKey}#{answered.entryNo}
        </Link>
      </p>

      <div className={styles.body}>
        <Markdown>{answered.body}</Markdown>
      </div>

      <button className={styles.close} type="button" onClick={onClose}>
        Закрыть
      </button>
    </section>
  );
}
