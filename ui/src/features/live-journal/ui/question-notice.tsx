import { Link } from 'react-router';
import { Badge } from '@/shared/ui';
import { cn } from '@/shared/lib';
import { taskRefHref } from '@/shared/lib/task-refs';
import type { LiveJournal } from '../model/use-live-journal';

/**
 * Вопросы, адресованные этому человеку и пришедшие при открытом приложении.
 *
 * Ответ на вопрос — единственное, ради чего человек в трекере что-то делает
 * (`CONCEPT.md`, 1), поэтому это единственное событие, которому позволено привлекать
 * внимание движением. Оно же единственное, что не должно двигать чужое: место у стопки
 * своё, вне потока вёрстки, — появление уведомления не смещает ни шапку, ни таблицу.
 *
 * Уведомление живёт, пока человек его не закрыл или не перешёл по нему. По таймеру
 * не гаснет намеренно: пропущенное уведомление хуже отсутствующего — человек, который
 * отвернулся на минуту, не узнал бы, что его спрашивали.
 */
export function QuestionNotice({
  incomingQuestions,
  dismissQuestion,
}: Pick<LiveJournal, 'incomingQuestions' | 'dismissQuestion'>) {
  return (
    // Стопка существует всегда, даже пустая, и `aria-live` стоит на ней, а не на
    // карточке: экранный диктор объявляет изменения внутри области, которую он уже
    // наблюдает. Область, появившаяся вместе со своим текстом, не объявляется вовсе —
    // объявлять было нечего в тот момент, когда её начали наблюдать.
    //
    // Пустая стопка ничего не занимает: она вне потока вёрстки и без содержимого
    // не имеет размеров.
    <aside
      /*
       * Стопка стоит вне потока вёрстки: уведомление, пришедшее само, не вправе
       * сдвинуть то, что человек читает. Место при этом своё и постоянное — в правом
       * нижнем углу его не закрывает ни шапка, ни первые строки таблицы, которые и
       * читают в первую очередь. Предел ширины общий с полосой обновлений.
       */
      className="fixed right-4 bottom-4 z-10 flex max-w-(--ui-float-max) flex-col gap-2"
      aria-label="Вопросы ко мне"
      aria-live="polite"
    >
      {incomingQuestions.map((question) => (
        <article
          className={cn(
            'relative rounded-control border border-attention-line bg-attention-soft',
            'py-3 pr-8 pl-3 text-attention shadow-raised',
            /*
             * Единственное движение, начинающееся само: один раз, на появление. Это
             * ровно то событие, ради которого движение вообще заведено. Само правило
             * живёт токеном `--animate-appear` в `shared/styles/theme.css` — в Tailwind 4
             * движение такая же часть темы, как цвет и радиус, — и прозрачности в нём
             * нет намеренно: она роняла контраст ниже AA на промежуточных кадрах.
             * При `prefers-reduced-motion` общее правило в `shared/styles/index.css`
             * сводит движение к мгновенному — уведомление просто есть.
             */
            'animate-appear',
          )}
          key={question.id}
        >
          <p className="mb-1 flex items-center gap-2">
            <Link
              // Цвет от карточки, а не ссылочный акцент: янтарный текст уведомления
              // подобран под его же заливку, и синяя ссылка выпала бы из пары.
              className="font-mono text-meta font-semibold text-inherit"
              to={taskRefHref({ key: question.taskKey, entryNo: question.no })}
              onClick={() => dismissQuestion(question.id)}
            >
              {question.taskKey}#{question.no}
            </Link>
            {question.blocking ? (
              <Badge tone="danger" title="Работа по задаче стоит без ответа">
                блокирующий
              </Badge>
            ) : null}
          </p>

          {/* Длинный заголовок не растит карточку без предела и не обрезается
              посреди слова. */}
          <p className="text-meta wrap-anywhere">{question.title}</p>

          <button
            className={cn(
              'absolute top-1 right-1 rounded-mark border border-transparent bg-transparent',
              // Цвет не назван: сброс уже отдаёт кнопке `color: inherit`, и `text-inherit`
              // повторил бы то, что и так есть.
              'px-2 py-0 text-screen leading-[1.4]',
              // Отклик на наведение: рамка проступает цветом текста карточки.
              'transition-[border-color] duration-(--motion-fast) ease-fast',
              'hover:border-current',
            )}
            type="button"
            onClick={() => dismissQuestion(question.id)}
            aria-label={`Закрыть уведомление о вопросе ${question.taskKey}#${question.no}`}
          >
            ×
          </button>
        </article>
      ))}
    </aside>
  );
}
