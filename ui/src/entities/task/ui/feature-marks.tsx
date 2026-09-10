import { CircleHelp, Flag, Lock } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useLanguage } from '@/shared/i18n';
import { formatNumber } from '@/shared/lib';
import type { TaskFeatures } from '../api/tasks';

/**
 * Признаки строки знаками с числом. Признак важнее тега: он говорит, что задача
 * заблокирована, что её кто-то ждёт, что человек оставил замечание, — и в списке
 * из тридцати восьми строк обязан цеплять взгляд, а не выглядеть ещё одной серой
 * плашкой рядом с тегами.
 *
 * Ничего не вычисляется: `features` считает бэкенд, интерфейс не выдумывает за него
 * (`CONCEPT.md`, 6).
 *
 * Знаков три, а признаков в контракте четыре: блокирующие вопросы — не отдельный
 * знак, а состояние знака вопросов. Четвёртый значок рядом с третьим перестаёт
 * читаться, а различие «вопрос есть» и «вопрос держит работу» важнее, чем ещё одно
 * число: поэтому оно меняет тон знака и его доступное имя.
 */
function Mark({
  icon: Icon,
  label,
  tone,
  count,
}: {
  icon: typeof Lock;
  label: string;
  tone: string;
  /**
   * `null` — признак без числа: он либо есть, либо нет. Число приходит уже собранным
   * на языке интерфейса: разделитель разрядов у языков разный.
   */
  count: string | null;
}) {
  return (
    <span
      data-mark="feature"
      className={`inline-flex items-center gap-1 whitespace-nowrap text-mark ${tone}`}
      title={label}
    >
      <Icon className="size-(--ui-mark) shrink-0" aria-hidden="true" />
      <span className="sr-only">{label}</span>
      {count === null ? null : <span aria-hidden="true">{count}</span>}
    </span>
  );
}

export function TaskFeatureMarks({ features }: { features: TaskFeatures }) {
  const blocking = features.open_blocking_questions;
  const { t } = useTranslation('ui');
  const { language } = useLanguage();

  return (
    <>
      {features.blocked ? (
        <Mark icon={Lock} label={t('task.features.blocked')} tone="text-danger" count={null} />
      ) : null}

      {features.open_questions > 0 ? (
        <Mark
          icon={CircleHelp}
          /*
           * Два числа в одной фразе, и склоняются они порознь: `i18next` считает форму
           * по одному `count`, поэтому второе приходит уже собранной фразой. Порядок
           * кусков при этом задаёт словарь, а не эта строка, — склейки здесь нет.
           */
          label={
            blocking > 0
              ? t('task.features.questionsBlocking', {
                  count: features.open_questions,
                  blocking: t('task.features.blockingOf', { count: blocking }),
                })
              : t('task.features.questions', { count: features.open_questions })
          }
          tone={blocking > 0 ? 'text-danger' : 'text-attention'}
          count={formatNumber(features.open_questions, language)}
        />
      ) : null}

      {/*
       * Замечание ничего не останавливает, поэтому тон акцента, а не опасности:
       * человек сказал «вышло не то», и это ждёт разбора, а не спасения.
       */}
      {features.open_remarks > 0 ? (
        <Mark
          icon={Flag}
          label={t('task.features.remarks', { count: features.open_remarks })}
          tone="text-accent"
          count={formatNumber(features.open_remarks, language)}
        />
      ) : null}
    </>
  );
}
