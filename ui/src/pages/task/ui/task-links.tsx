import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import type { LinkKind, TaskLink } from '@/entities/task';
import { Badge } from '@/shared/ui';

/**
 * Связи с обеих сторон. Вид назван от лица этой задачи, статус — у той, что на другом
 * конце: именно из `blocked_by` на незакрытую задачу бэкенд считает признак «заблокирована».
 */
export function TaskLinks({ links }: { links: TaskLink[] }) {
  const { t } = useTranslation('task');

  if (links.length === 0) return <p className="text-muted italic">{t('noLinks')}</p>;

  const byKind = new Map<LinkKind, TaskLink[]>();
  for (const link of links) {
    const same = byKind.get(link.kind) ?? [];
    same.push(link);
    byKind.set(link.kind, same);
  }

  return (
    /*
     * Связи — список внутри поверхности карточки (решение Д11), поэтому свои поля
     * держит он сам: у блока-списка их нет, иначе строки не доходили бы до краёв.
     */
    <div className="flex flex-col gap-3 p-3">
      {[...byKind].map(([kind, group]) => (
        <div key={kind} className="flex items-baseline gap-3">
          <Badge mono>{kind}</Badge>
          <ul className="flex list-none flex-col gap-1 p-0">
            {group.map((link) => (
              <li key={link.other.key} className="flex flex-wrap items-baseline gap-2">
                <Link className="font-mono" to={`/tasks/${link.other.key}`}>
                  {link.other.key}
                </Link>
                <span className="text-muted">{link.other.title}</span>
                <Badge mono>{link.other.status}</Badge>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}
