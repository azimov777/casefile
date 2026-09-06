import { useEffect, useId, useState, type FormEvent } from 'react';
import { ApiError } from '@/shared/api';
import { errorMessage } from '@/shared/errors';
import { Button, Callout, Markdown } from '@/shared/ui';
import {
  EMPTY_DRAFT,
  clearDraft,
  draftKey,
  readDraft,
  saveDraft,
  type AnswerDraft,
} from '../model/draft';
import type { Answered } from '../model/answering';
import { useAnswerQuestion } from '../model/use-answer-question';
import styles from './answer-form.module.css';

interface AnswerFormProps {
  taskKey: string;
  questionNo: number;
  /**
   * Отправка началась. Зовётся **до** запроса и синхронно: вызывающий обязан успеть
   * закрепить вопрос на экране раньше, чем перечитывание сможет его оттуда убрать.
   */
  onBegin?: () => void;
  /** Ответ подшит: номер записи и текст, каким он ушёл. */
  onAnswered?: (answered: Answered) => void;
  /** Отправка не удалась: закрепление можно снять, черновик остаётся в форме. */
  onFailed?: () => void;
}

/**
 * Форма ответа на вопрос агента — единственная форма записи, какая есть у человека
 * (`CONCEPT.md`, 1).
 *
 * Черновик пишется в `sessionStorage` на каждое изменение: человек уходит смотреть
 * соседнюю задачу и возвращается дописывать.
 *
 * Своего подтверждения форма не показывает и показать не может: удачный ответ убирает
 * вопрос из выдачи, и форма размонтируется вместе с ним. Исход она сообщает наружу,
 * а рисует его тот, кто переживает перечитывание, — страница.
 */
export function AnswerForm({
  taskKey,
  questionNo,
  onBegin,
  onAnswered,
  onFailed,
}: AnswerFormProps) {
  const storageKey = draftKey(taskKey, questionNo);
  const [draft, setDraft] = useState<AnswerDraft>(() => readDraft(storageKey));
  const [showPreview, setShowPreview] = useState(false);
  const [emptyBody, setEmptyBody] = useState(false);
  const answer = useAnswerQuestion();

  const bodyId = useId();

  // Форма живёт под каждым вопросом, и вопрос может смениться без перемонтирования.
  useEffect(() => {
    setDraft(readDraft(storageKey));
    setEmptyBody(false);
  }, [storageKey]);

  function change(changes: Partial<AnswerDraft>) {
    const next = { ...draft, ...changes };
    setDraft(next);
    saveDraft(storageKey, next);

    // Упрёк снимается первым же введённым символом. Сообщение, висящее над полем,
    // в которое человек уже пишет, — это не подсказка, а штраф за прошлое: он
    // сделал ровно то, о чём его попросили, и продолжает видеть красное.
    if (emptyBody && next.body.trim() !== '') setEmptyBody(false);
    if (answer.isError) answer.reset();
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (draft.body.trim() === '') {
      setEmptyBody(true);
      return;
    }
    setEmptyBody(false);

    // Ключ повтора рождается на первой попытке и переживает её провал: повторная
    // отправка того же черновика идёт с тем же ключом и не заводит второй ответ.
    const idempotencyKey = draft.idempotencyKey === '' ? crypto.randomUUID() : draft.idempotencyKey;
    if (draft.idempotencyKey === '') change({ idempotencyKey });

    const body = draft.body.trim();
    // Раньше запроса и синхронно: дальше начинается гонка кадра потока с ответом
    // сервера, и к её началу вопрос обязан быть закреплён на экране.
    onBegin?.();

    answer.mutate(
      { taskKey, questionNo, body, idempotencyKey },
      {
        onSuccess: (entry) => {
          clearDraft(storageKey);
          setDraft(EMPTY_DRAFT);
          setShowPreview(false);
          onAnswered?.({ entryNo: entry.no, body });
        },
        onError: () => onFailed?.(),
      },
    );
  }

  const fields = answer.error instanceof ApiError ? answer.error.fields : null;
  const problem = emptyBody
    ? 'Пустой ответ отправить нельзя: агенту нужен текст, а не факт нажатия кнопки.'
    : fields?.body;

  return (
    <form
      className={styles.form}
      onSubmit={submit}
      aria-label={`Ответ на ${taskKey}#${questionNo}`}
    >
      <div className={styles.field}>
        <label className={styles.label} htmlFor={bodyId}>
          Ответ
        </label>
        <textarea
          id={bodyId}
          className={styles.textarea}
          value={draft.body}
          onChange={(event) => change({ body: event.target.value })}
          rows={5}
          placeholder="Markdown. Ссылки вида DEMO-2 и DEMO-2#7 станут ссылками."
          aria-invalid={problem !== undefined}
          aria-describedby={problem === undefined ? undefined : `${bodyId}-problem`}
        />
      </div>

      {/*
       * Всё, что может появиться и исчезнуть, стоит НИЖЕ кнопок: и упрёк, и
       * предпросмотр, и отказ отправки. Резервировать под них место сверху не нужно —
       * растёт только то, что под кнопками, и «Ответить» не сдвигается ни на пиксель
       * ни в одном состоянии формы. Раньше упрёк опускал её на 24 px, а предпросмотр
       * ещё на 140 — прямо из-под пальца человека, который сейчас нажмёт ещё раз
       * (`docs/notes/ui.md`, про экран входа).
       *
       * Упрёк при этом не отрывается от поля: связь держит `aria-describedby`,
       * а глазами он читается там, где человек только что нажал.
       */}
      <div className={styles.actions}>
        <Button type="submit" disabled={answer.isPending}>
          {answer.isPending ? 'Отправляем…' : 'Ответить'}
        </Button>
        <Button tone="quiet" onClick={() => setShowPreview(!showPreview)}>
          {showPreview ? 'Скрыть предпросмотр' : 'Предпросмотр'}
        </Button>
      </div>

      {problem === undefined ? null : (
        <span className={styles.problem} id={`${bodyId}-problem`} role="alert">
          {problem}
        </span>
      )}

      {showPreview && draft.body.trim() !== '' ? (
        <div className={styles.preview}>
          <span className={styles.label}>Как это увидит агент</span>
          <Markdown>{draft.body}</Markdown>
        </div>
      ) : null}

      {answer.isError ? (
        <Callout tone="danger">
          {errorMessage(answer.error)} Повторная отправка не заведёт второй ответ: ключ повтора у
          попытки тот же.
        </Callout>
      ) : null}
    </form>
  );
}
