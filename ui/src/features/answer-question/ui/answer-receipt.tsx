import { useTranslation } from 'react-i18next';
import { Receipt } from '@/shared/ui';
import type { Answered } from '../model/answering';

interface AnswerReceiptProps {
  taskKey: string;
  questionNo: number;
  answered: Answered;
  onClose: () => void;
}

/**
 * Подтверждение ответа: чем именно ответили и куда это легло.
 *
 * Вид общий с подтверждением замечания (`shared/ui`, `Receipt`); своё здесь — слова,
 * которыми названо случившееся, и адрес вопроса в метке.
 */
export function AnswerReceipt({ taskKey, questionNo, answered, onClose }: AnswerReceiptProps) {
  const { t } = useTranslation('ui');
  const reference = `${taskKey}#${questionNo}`;

  return (
    <Receipt
      label={t('answer.receiptLabel', { reference })}
      headline={t('answer.receiptHeadline')}
      taskKey={taskKey}
      entryNo={answered.entryNo}
      body={answered.body}
      onClose={onClose}
    />
  );
}
