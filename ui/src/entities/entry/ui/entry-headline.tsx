import { Link } from 'react-router';
import { taskRefHref } from '@/shared/lib';
import type { Headline, HeadlinePart } from '../model/headline';

/**
 * Собранная строка заголовка: слова по-русски, идентификаторы контракта как есть.
 *
 * Ничего не решает сама: что показывать, уже сказано в `Headline`. Здесь только то,
 * как выглядит каждая часть, — и это одно место на ленту дела и опись карточки.
 */
export function EntryHeadline({ headline, linked = true }: EntryHeadlineProps) {
  if (headline.kind !== 'built') return null;

  return (
    <span className="inline-flex flex-wrap items-baseline gap-x-2 gap-y-1">
      {headline.parts.map((part, index) => (
        <Piece key={index} part={part} linked={linked} />
      ))}
    </span>
  );
}

interface EntryHeadlineProps {
  headline: Headline;
  /**
   * Делать ли ключи ссылками. В описи карточки строка целиком — кнопка раскрытия
   * записи, и ссылка внутри неё была бы интерактивом внутри интерактива: `axe`
   * называет это `nested-interactive`, а с клавиатуры туда не попасть осмысленно.
   */
  linked?: boolean;
}

/**
 * Идентификатор контракта: не переводится и выглядит так же, как в адресе и у агента.
 * Кегль назван явно — сброс набирает `<code>` долей от окружающего текста, а здесь
 * идентификатор стоит и в шапке служебной записи, и в заголовке карточки.
 */
const IDENTIFIER = 'font-mono text-meta';

function Piece({ part, linked }: { part: HeadlinePart; linked: boolean }) {
  switch (part.kind) {
    case 'words':
      return <span>{part.text}</span>;
    case 'id':
      return <code className={IDENTIFIER}>{part.text}</code>;
    case 'task':
      return linked ? (
        <Link className={IDENTIFIER} to={`/tasks/${part.key}`}>
          {part.key}
        </Link>
      ) : (
        <code className={IDENTIFIER}>{part.key}</code>
      );
    case 'entry':
      return linked ? (
        <Link className={IDENTIFIER} to={taskRefHref({ key: part.key, entryNo: part.no })}>
          {part.key}#{part.no}
        </Link>
      ) : (
        <code className={IDENTIFIER}>
          {part.key}#{part.no}
        </code>
      );
  }
}
