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
  return (
    <Receipt
      label={`Ответ на ${taskKey}#${questionNo} подшит`}
      headline="Ответ подшит"
      taskKey={taskKey}
      entryNo={answered.entryNo}
      body={answered.body}
      onClose={onClose}
    />
  );
}
