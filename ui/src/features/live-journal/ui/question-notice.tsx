import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import { Badge } from '@/shared/ui';
import { cn, useExitHoldList } from '@/shared/lib';
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
 *
 * Движений здесь два, и они про разное. **Карточка** приходит и уходит своими именами
 * (`animate-appear`, `animate-disappear` в `shared/styles/theme.css`): сдвиг с
 * затуханием, вход `--motion-slow`, выход `--motion-fast` — выход отвечает человеку
 * и потому вдвое короче (`UI-59#11`). **Место** карточки в стопке едет отдельно,
 * строками сетки: `transform` места не занимает и не освобождает, и без второго
 * движения соседи по стопке прыгали бы на её высоту в один кадр — тот же дефект,
 * от которого уходило решение про сдвиг читаемого.
 */
export function QuestionNotice({
  incomingQuestions,
  dismissQuestion,
}: Pick<LiveJournal, 'incomingQuestions' | 'dismissQuestion'>) {
  /*
   * Узел обязан дожить до конца выхода, а `incomingQuestions` убирает карточку в том
   * же кадре, в котором человек нажал. Задержка размонтирования — общая на весь
   * интерфейс (`shared/lib/exit-hold.ts`), второй такой заводить нельзя. Списочная
   * форма держит стопку, редеющую по одному: закрытая карточка остаётся на своём
   * месте, а не перепрыгивает в конец.
   */
  const held = useExitHoldList(incomingQuestions, (question) => question.id);
  const { t } = useTranslation('ui');

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
       *
       * Промежутка между карточками здесь нет намеренно: `gap` держится, пока стоит
       * сосед, и остался бы восемью пикселями после того, как место карточки доехало
       * до нуля. Он переехал внутрь — `mt-2` на самой карточке.
       */
      className="fixed right-4 bottom-4 z-10 flex max-w-(--ui-float-max) flex-col"
      aria-label={t('live.questionsToMe')}
      aria-live="polite"
    >
      {held.map(({ key, item: question, leaving, entering }) => (
        <div
          key={key}
          // Опора для замеров: длительность и кривую движения места снимают с этого
          // узла, а не угадывают по вложенности.
          data-notice="place"
          /*
           * Место карточки в стопке. Едет строками сетки, а не `transform`-ом: только
           * они двигают **место**, а прыгают соседи именно из-за места (`UI-59#12`).
           * Вход длится столько же, сколько вход карточки, выход — столько же, сколько
           * её выход: это одно событие, а не два.
           *
           * `starting:` выдаётся только въезжающему: узлу, стоявшему с самого начала,
           * входа не положено — движение отвечает на событие (`CONCEPT.md`, 6), а
           * загрузка страницы событием не является.
           */
          className={cn(
            // Уходящая карточка держится нижнего края своего места: место закрывается
            // сверху, соседи съезжают на неё, а сама она стоит и гаснет.
            'grid items-end transition-[grid-template-rows]',
            leaving
              ? 'grid-rows-[0fr] duration-(--motion-fast) ease-exit'
              : 'grid-rows-[1fr] duration-(--motion-slow) ease-fast',
            !leaving && entering && 'starting:grid-rows-[0fr]',
          )}
        >
          {/*
            Прослойка без собственных полей. `min-h-0` обнуляет минимальный размер
            элемента сетки — без него строка `0fr` встала бы на высоте содержимого.
            Обрезанием (`overflow: hidden`, как у `Reveal`) этого добиваться нельзя:
            оно срезало бы тень карточки и не пустило бы её уехать за край места.

            Отступ живёт на карточке, а не здесь: минимальный вклад элемента сетки
            считается по внешнему размеру, и поле оставило бы строку `0fr` на восьми
            пикселях вместо нуля.
          */}
          <div className="min-h-0">
            <article
              className={cn(
                'relative mt-2 rounded-control border border-attention-line bg-attention-soft',
                'py-3 pr-8 pl-3 text-attention shadow-raised',
                /*
                 * Приход — единственное движение, начинающееся само: это ровно то
                 * событие, ради которого движение вообще заведено. Уход зеркалит его
                 * и вдвое короче. Оба живут токенами в `shared/styles/theme.css` —
                 * в Tailwind 4 движение такая же часть темы, как цвет и радиус.
                 * При `prefers-reduced-motion` общее правило в
                 * `shared/styles/index.css` сводит оба к мгновенному: уведомление
                 * просто есть, а потом его просто нет.
                 */
                leaving ? 'animate-disappear' : entering && 'animate-appear',
              )}
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
                  <Badge tone="danger" title={t('live.blockingTitle')}>
                    {t('live.blockingBadge')}
                  </Badge>
                ) : null}
              </p>

              {/* Длинный заголовок не растит карточку без предела и не обрезается
                  посреди слова. */}
              <p className="text-meta wrap-anywhere">{question.title}</p>

              <button
                className={cn(
                  'absolute top-1 right-1 rounded-mark border border-transparent bg-transparent',
                  // Цвет не назван: сброс уже отдаёт кнопке `color: inherit`, и
                  // `text-inherit` повторил бы то, что и так есть.
                  'px-2 py-0 text-screen leading-[1.4]',
                  // Отклик на наведение: рамка проступает цветом текста карточки.
                  'transition-[border-color] duration-(--motion-fast) ease-fast',
                  'hover:border-current',
                )}
                type="button"
                onClick={() => dismissQuestion(question.id)}
                aria-label={t('live.dismiss', {
                  reference: `${question.taskKey}#${question.no}`,
                })}
              >
                ×
              </button>
            </article>
          </div>
        </div>
      ))}
    </aside>
  );
}
