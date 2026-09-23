import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ApiError } from '@/shared/api';
import { errorMessage } from '@/shared/errors';
import { Composer, Receipt } from '@/shared/ui';
import { remarkDraftKey } from '../model/draft';
import { remarkTitle, useLeaveRemark } from '../model/use-leave-remark';

interface RemarkFormProps {
  taskKey: string;
  /**
   * Отмена: черновик уже выброшен, форме остаётся только свернуться. Родитель решает,
   * как это выглядит, — на карточке задачи форма попросту размонтируется.
   */
  onCancel: () => void;
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
export function RemarkForm({ taskKey, onCancel }: RemarkFormProps) {
  const remark = useLeaveRemark();
  const [filed, setFiled] = useState<{ entryNo: number; body: string } | null>(null);
  const fields = remark.error instanceof ApiError ? remark.error.fields : null;
  // И ради подписи, и ради подписки на язык: текст отказа берёт язык у экземпляра.
  const { t } = useTranslation('ui');

  if (filed !== null) {
    return (
      <Receipt
        label={t('remark.receiptLabel', { key: taskKey })}
        headline={t('remark.receiptHeadline')}
        taskKey={taskKey}
        entryNo={filed.entryNo}
        body={filed.body}
        onClose={() => setFiled(null)}
      />
    );
  }

  return (
    <Composer
      label={t('remark.formLabel', { key: taskKey })}
      fieldLabel={t('remark.fieldLabel')}
      storageKey={remarkDraftKey(taskKey)}
      submitLabel={t('remark.submit')}
      pendingLabel={t('remark.pending')}
      emptyProblem={t('remark.empty')}
      placeholder={t('remark.placeholder')}
      problem={fields?.body ?? fields?.title}
      isPending={remark.isPending}
      onCancel={onCancel}
      failure={
        remark.isError ? (
          <>
            {errorMessage(remark.error)} {t('remark.retrySafe')}
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
