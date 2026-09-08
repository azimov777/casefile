import { Link } from 'react-router';
import { taskRefHref } from '@/shared/lib/task-refs';
import { Markdown } from './markdown';

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
    <section
      className="rounded-control border border-positive-line bg-positive-soft p-3"
      aria-label={label}
    >
      <p className="mb-2 flex items-baseline gap-3">
        <span className="font-semibold text-positive">{headline}</span>
        {/* Номер записи — из ответа сервера: по этой ссылке запись действительно лежит. */}
        <Link className="font-mono text-meta" to={taskRefHref({ key: taskKey, entryNo })}>
          {taskKey}#{entryNo}
        </Link>
      </p>

      {/*
       * Высота подтверждения держится близко к высоте формы, которую оно заменило:
       * иначе ответ схлопывал бы блок под руками — ровно та беда, ради которой всё это
       * и делалось. Нижняя граница не даёт короткому ответу оставить дыру, верхняя —
       * длинному растянуть страницу; между ними прокрутка, а не обрезание. Текст,
       * который человек только что написал, обрезать нельзя.
       */}
      <div className="max-h-36 min-h-24 overflow-y-auto text-meta">
        <Markdown>{body}</Markdown>
      </div>

      <button
        className="mt-2 rounded-mark border border-positive-line bg-transparent px-2 py-0 text-meta text-positive transition-colors duration-(--motion-fast) ease-fast hover:bg-surface"
        type="button"
        onClick={onClose}
      >
        Закрыть
      </button>
    </section>
  );
}
