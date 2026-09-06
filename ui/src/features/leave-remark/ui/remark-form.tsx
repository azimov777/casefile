import { useState } from 'react';
import { ApiError } from '@/shared/api';
import { errorMessage } from '@/shared/errors';
import { Composer, Receipt } from '@/shared/ui';
import { remarkDraftKey } from '../model/draft';
import { remarkTitle, useLeaveRemark } from '../model/use-leave-remark';

interface RemarkFormProps {
  taskKey: string;
}

/**
 * Форма замечания: «вышло не то» о задаче целиком.
 *
 * Стоит на карточке задачи вне списка замечаний — и это не оформление, а условие
 * работоспособности. Форма ответа живёт под своим вопросом, и удачная отправка
 * уносит её вместе с вопросом из выдачи; поэтому подтверждение ответа рисует
 * страница. У замечания такой беды нет: форма не привязана ни к какому элементу
 * выдачи, переживает перечитывание пакета и показывает исход сама — в том числе
 * когда кадр живого потока пришёл раньше ответа сервера.
 *
 * Заголовок отдельным полем не спрашивается: он выводится из первой строки текста
 * (`remarkTitle`). Человеку, который увидел «вышло не то», надо сказать это одним
 * действием, а не заполнить два поля.
 */
export function RemarkForm({ taskKey }: RemarkFormProps) {
  const remark = useLeaveRemark();
  const [filed, setFiled] = useState<{ entryNo: number; body: string } | null>(null);
  const fields = remark.error instanceof ApiError ? remark.error.fields : null;

  if (filed !== null) {
    return (
      <Receipt
        label={`Замечание к ${taskKey} подшито`}
        headline="Замечание подшито"
        taskKey={taskKey}
        entryNo={filed.entryNo}
        body={filed.body}
        onClose={() => setFiled(null)}
      />
    );
  }

  return (
    <Composer
      label={`Замечание к ${taskKey}`}
      fieldLabel="Замечание"
      storageKey={remarkDraftKey(taskKey)}
      submitLabel="Оставить замечание"
      pendingLabel="Отправляем…"
      emptyProblem="Пустое замечание отправить нельзя: агенту нужно знать, что именно не так."
      placeholder="Что вышло не так. Markdown; ссылки вида DEMO-2 и DEMO-2#7 станут ссылками."
      problem={fields?.body ?? fields?.title}
      isPending={remark.isPending}
      failure={
        remark.isError ? (
          <>
            {errorMessage(remark.error)} Повторная отправка не заведёт второе замечание: ключ
            повтора у попытки тот же.
          </>
        ) : undefined
      }
      onSubmit={async (body, idempotencyKey) => {
        try {
          const entry = await remark.mutateAsync({
            taskKey,
            title: remarkTitle(body),
            body,
            idempotencyKey,
          });
          setFiled({ entryNo: entry.no, body });
          return true;
        } catch {
          // Что случилось, скажет `failure`; черновик при этом остаётся в форме.
          return false;
        }
      }}
    />
  );
}
