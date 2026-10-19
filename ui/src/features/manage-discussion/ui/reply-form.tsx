import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { DiscussionOption } from '@/entities/discussion';
import { ApiError } from '@/shared/api';
import { errorMessage, fieldReasonText } from '@/shared/errors';
import { Composer } from '@/shared/ui';
import { replyDraftKey } from '../model/draft';
import { useReply } from '../model/use-discussion-actions';
import { OptionPicker } from './option-picker';

/**
 * Форма «Ответить на #N»: ответ человека на вопрос обсуждения.
 *
 * Ввод, черновик и предпросмотр — общие с остальными формами записи (`Composer`). В отличие
 * от ответа в деле задачи, форма не уходит вместе с вопросом: вопрос остаётся в ленте
 * обсуждения с пометкой «отвечено», и удачную отправку форма подтверждает сама.
 *
 * Если агент приложил к вопросу варианты (`options`), над полем текста встают радио-карточки:
 * ответить можно выбором, текстом или тем и другим, и пустой текст при выборе допустим.
 * Вопрос без вариантов выглядит и работает как прежде.
 */
export function ReplyForm({
  address,
  questionNo,
  options,
  onCancel,
}: {
  address: string;
  questionNo: number;
  options?: DiscussionOption[] | null;
  onCancel: () => void;
}) {
  const reply = useReply();
  const [choice, setChoice] = useState<string | null>(null);
  const fields = reply.error instanceof ApiError ? reply.error.fields : null;
  const { t } = useTranslation('discussions');
  const hasOptions = options != null && options.length > 0;

  return (
    <Composer
      label={t('reply.formLabel', { reference: `${address}#${questionNo}` })}
      fieldLabel={hasOptions ? t('reply.optionsField') : t('reply.fieldLabel')}
      storageKey={replyDraftKey(address, questionNo)}
      submitLabel={t('reply.submit')}
      pendingLabel={t('reply.pending')}
      emptyProblem={hasOptions ? t('reply.emptyWithOptions') : t('reply.empty')}
      allowEmpty={choice !== null}
      lead={
        hasOptions ? (
          <OptionPicker options={options} value={choice} onChange={setChoice} />
        ) : undefined
      }
      placeholder={t('reply.placeholder')}
      problem={fields?.body === undefined ? undefined : fieldReasonText(fields.body)}
      isPending={reply.isPending}
      onCancel={onCancel}
      failure={
        reply.isError ? (
          <>
            {errorMessage(reply.error)} {t('retrySafe')}
          </>
        ) : undefined
      }
      onSubmit={async (body, idempotencyKey) => {
        try {
          await reply.mutateAsync({
            address,
            questionNo,
            body,
            idempotencyKey,
            ...(choice === null ? {} : { choice }),
          });
          return true;
        } catch {
          return false;
        }
      }}
    />
  );
}
