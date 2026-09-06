import { Link } from 'react-router';
import { taskRefHref } from '@/shared/lib/task-refs';
import { Markdown } from './markdown';
import styles from './receipt.module.css';

interface ReceiptProps {
  /** Метка для программы чтения с экрана: «Ответ на DEMO-1#7 подшит». */
  label: string;
  /** Что случилось, словами: «Ответ подшит», «Замечание подшито». */
  headline: string;
  taskKey: string;
  /** Номер подшитой записи — из ответа сервера, не вычисленный. */
  entryNo: number;
  body: string;
  onClose: () => void;
}

/**
 * Подтверждение: запись подшита, вот её номер и вот что в ней написано.
 *
 * Стоит на месте формы, а не на новом экране: человек видит, что он отправил и куда
 * это легло, одним взглядом. Раньше подтверждения не было вовсе — блок с вопросом и
 * формой просто исчезал, и единственным признаком, что что-то произошло, был счётчик
 * в шапке.
 *
 * Не гаснет по таймеру: подтверждение, которое человек не успел прочитать, ничем не
 * лучше отсутствующего. Общий для ответа и замечания: подтверждают они одно и то же —
 * «страница подшита, вот её адрес».
 */
export function Receipt({ label, headline, taskKey, entryNo, body, onClose }: ReceiptProps) {
  return (
    <section className={styles.receipt} aria-label={label}>
      <p className={styles.head}>
        <span className={styles.done}>{headline}</span>
        {/* Номер записи — из ответа сервера: по этой ссылке запись действительно лежит. */}
        <Link className={styles.entry} to={taskRefHref({ key: taskKey, entryNo })}>
          {taskKey}#{entryNo}
        </Link>
      </p>

      <div className={styles.body}>
        <Markdown>{body}</Markdown>
      </div>

      <button className={styles.close} type="button" onClick={onClose}>
        Закрыть
      </button>
    </section>
  );
}
