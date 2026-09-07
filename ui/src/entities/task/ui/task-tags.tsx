import { Badge } from '@/shared/ui';

/** Сколько тегов показываем: остальные уходят в счётчик. */
const SHOWN = 2;

/**
 * Теги строки: первые два и счётчик остальных.
 *
 * Обрезание без доступа к скрытому было бы потерей данных, а не плотностью, поэтому
 * счётчик называет скрытые теги поимённо — и в подсказке, и в доступном имени.
 * Показывать все нельзя: на широком экране колонка расширяется под самый длинный
 * набор и отнимает ширину у названия, на узком — переносит строку (решение Д4).
 */
export function TaskTags({ tags }: { tags: string[] }) {
  const shown = tags.slice(0, SHOWN);
  const hidden = tags.slice(SHOWN);

  return (
    <span className="flex items-center gap-1 overflow-hidden">
      {shown.map((tag) => (
        <Badge key={tag} mono>
          {tag}
        </Badge>
      ))}
      {hidden.length === 0 ? null : (
        <span className="shrink-0 text-mark text-faint" title={`Ещё теги: ${hidden.join(', ')}`}>
          <span aria-hidden="true">+{hidden.length}</span>
          <span className="sr-only">ещё теги: {hidden.join(', ')}</span>
        </span>
      )}
    </span>
  );
}
