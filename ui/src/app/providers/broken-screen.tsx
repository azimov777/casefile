import { useTranslation } from 'react-i18next';
import { Button } from '@/shared/ui';

/**
 * Объяснение упавшего экрана.
 *
 * Отдельным файлом, а не соседом границы ошибок: подписи берутся хуком, а граница —
 * класс (ловить исключение из потомков умеет только `getDerivedStateFromError`,
 * и хука в нём не бывает). Держать рядом класс и компонент с хуком мешает горячей
 * перезагрузке — на это ругается `react-refresh/only-export-components`.
 */
export function BrokenScreen() {
  const { t } = useTranslation('ui');

  return (
    <div
      role="alert"
      className="mx-auto my-8 flex max-w-168 flex-col items-start gap-3 rounded-control border border-danger-line bg-danger-soft p-6"
    >
      <h1 className="text-title text-danger">{t('app.broken.title')}</h1>
      {/* Тоном отказа окрашен только заголовок: объяснение — обычный текст, и цвет
          содержания на цветной заливке назван явно, чтобы он не унаследовал тон. */}
      <p className="text-text">{t('app.broken.text')}</p>
      <Button onClick={() => window.location.reload()}>{t('app.broken.reload')}</Button>
    </div>
  );
}
