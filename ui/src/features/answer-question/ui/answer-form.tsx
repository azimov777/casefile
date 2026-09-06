import { ApiError } from '@/shared/api';
import { errorMessage } from '@/shared/errors';
import { Composer } from '@/shared/ui';
import { draftKey } from '../model/draft';
import type { Answered } from '../model/answering';
import { useAnswerQuestion } from '../model/use-answer-question';

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
 * Форма ответа на вопрос агента.
 *
 * Ввод, черновик и предпросмотр — общие с формой замечания и живут в `shared/ui`
 * (`Composer`). Здесь остаётся то, что у ответа своё: куда отправлять, чем упрекать
 * за пустоту и что сказать наружу об исходе.
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
  const answer = useAnswerQuestion();
  const fields = answer.error instanceof ApiError ? answer.error.fields : null;

  return (
    <Composer
      label={`Ответ на ${taskKey}#${questionNo}`}
      fieldLabel="Ответ"
      storageKey={draftKey(taskKey, questionNo)}
      submitLabel="Ответить"
      pendingLabel="Отправляем…"
      emptyProblem="Пустой ответ отправить нельзя: агенту нужен текст, а не факт нажатия кнопки."
      placeholder="Markdown. Ссылки вида DEMO-2 и DEMO-2#7 станут ссылками."
      problem={fields?.body}
      isPending={answer.isPending}
      failure={
        answer.isError ? (
          <>
            {errorMessage(answer.error)} Повторная отправка не заведёт второй ответ: ключ повтора у
            попытки тот же.
          </>
        ) : undefined
      }
      onBegin={onBegin}
      onSubmit={async (body, idempotencyKey) => {
        try {
          const entry = await answer.mutateAsync({ taskKey, questionNo, body, idempotencyKey });
          onAnswered?.({ entryNo: entry.no, body });
          return true;
        } catch {
          // Что именно случилось, покажет `failure` из состояния мутации; здесь важно
          // только снять закрепление и оставить черновик в форме.
          onFailed?.();
          return false;
        }
      }}
    />
  );
}
