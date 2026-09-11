import { useCallback, useState } from 'react';

/**
 * Отправленный ответ: то, чем подтверждается, что он подшит.
 *
 * Номер записи приходит из ответа сервера и на клиенте не вычисляется
 * (`CONCEPT.md`, 6): угаданный номер увёл бы человека не туда.
 */
export interface Answered {
  entryNo: number;
  body: string;
}

/**
 * Что известно про вопрос, по которому человек уже нажал «Ответить».
 *
 * `at` — место вопроса в списке на момент отправки. Без него закреплённый вопрос,
 * ушедший из выдачи, дописывался бы в конец и прыгал вниз ровно в тот момент, когда
 * человек на него смотрит, — та самая перестановка под руками, против которой всё
 * это и делается.
 */
type Progress<Q> =
  | { status: 'sending'; question: Q; at: number }
  | { status: 'answered'; question: Q; at: number; answered: Answered };

export interface Answering<Q> {
  /**
   * Вопросы, отправка по которым началась, вместе с их местом в списке. Страница
   * показывает их даже тогда, когда выдача их уже не содержит.
   */
  held: { question: Q; at: number }[];
  /** Подшитый ответ на этот вопрос, если он уже пришёл. */
  answerOf: (id: string) => Answered | undefined;
  isHeld: (id: string) => boolean;
  /** Отправка началась: вопрос закрепляется на экране до решения человека. */
  begin: (id: string, question: Q, at: number) => void;
  /** Ответ подшит: показываем подтверждение вместо формы. */
  complete: (id: string, answered: Answered) => void;
  /** Отправка не удалась: закрепление снимается, форма остаётся с черновиком. */
  fail: (id: string) => void;
  /** Человек прочитал подтверждение и закрыл его. */
  close: (id: string) => void;
}

/**
 * Судьба вопросов, по которым человек нажал «Ответить», — на уровне страницы,
 * а не внутри строки списка.
 *
 * Зачем так. Форма ответа стоит под своим вопросом, а вопрос приходит из выдачи.
 * Удачный ответ убирает вопрос из выдачи — значит строка размонтируется и уносит
 * с собой всё, что знала, в том числе «ответ ушёл, вот его номер». Хуже того, кадр
 * живого потока о той же записи перечитывает выдачу и может опередить ответ POST:
 * тогда форма исчезает раньше, чем узнаёт свой исход.
 *
 * Поэтому вопрос закрепляется **в момент отправки**, до того как гонка началась,
 * и держится на экране, пока человек сам не закроет подтверждение. Порядок прихода
 * кадра и ответа сервера после этого перестаёт что-либо значить.
 */
export function useAnswering<Q>(): Answering<Q> {
  const [progress, setProgress] = useState<Record<string, Progress<Q>>>({});

  const begin = useCallback((id: string, question: Q, at: number) => {
    setProgress((current) => ({ ...current, [id]: { status: 'sending', question, at } }));
  }, []);

  const complete = useCallback((id: string, answered: Answered) => {
    setProgress((current) => {
      const held = current[id];
      if (held === undefined) return current;
      return {
        ...current,
        [id]: { status: 'answered', question: held.question, at: held.at, answered },
      };
    });
  }, []);

  const drop = useCallback((id: string) => {
    setProgress((current) => {
      if (current[id] === undefined) return current;
      return Object.fromEntries(Object.entries(current).filter(([key]) => key !== id));
    });
  }, []);

  return {
    held: Object.values(progress).map(({ question, at }) => ({ question, at })),
    answerOf: (id) => {
      const held = progress[id];
      return held?.status === 'answered' ? held.answered : undefined;
    },
    isHeld: (id) => progress[id] !== undefined,
    begin,
    complete,
    fail: drop,
    close: drop,
  };
}

/**
 * Список вопросов с возвращёнными на свои места закреплёнными.
 *
 * Закреплённый вопрос, которого в выдаче больше нет, встаёт туда, где он был в момент
 * отправки, а не в конец: человек отвечает на вопрос и продолжает видеть его там же,
 * где видел секунду назад.
 */
export function withHeld<Q>(
  items: Q[],
  held: { question: Q; at: number }[],
  idOf: (question: Q) => string,
): Q[] {
  const present = new Set(items.map(idOf));
  const missing = held
    .filter(({ question }) => !present.has(idOf(question)))
    .sort((left, right) => left.at - right.at);

  const merged = [...items];
  for (const { question, at } of missing) merged.splice(Math.min(at, merged.length), 0, question);
  return merged;
}
