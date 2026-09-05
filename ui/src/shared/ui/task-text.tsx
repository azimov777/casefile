import { Link } from 'react-router';
import { splitTaskRefs, taskRefHref } from '../lib';

/**
 * Строка обычного текста, в которой `TRK-42` и `TRK-42#12` стали ссылками.
 * Для заголовков описи и прочих мест, где markdown не рисуется.
 */
export function TaskText({ children }: { children: string }) {
  return (
    <>
      {splitTaskRefs(children).map((part, index) =>
        part.kind === 'text' ? (
          part.value
        ) : (
          // Ключ по позиции: части одной строки не переупорядочиваются и не удаляются.
          <Link key={index} to={taskRefHref(part.ref)}>
            {part.value}
          </Link>
        ),
      )}
    </>
  );
}
