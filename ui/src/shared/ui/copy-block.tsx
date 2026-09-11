import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Check, Copy } from 'lucide-react';
import { Button } from './button';

interface CopyBlockProps {
  /**
   * Что лежит в блоке, словами: «Команда Claude Code». Им названа кнопка для программы
   * чтения с экрана — пять одинаковых «Копировать» подряд не сказали бы, что копируется.
   */
  label: string;
  /** Подпись над текстом: куда его вставлять — файл, терминал, поле. */
  caption: string;
  /** Текст, который уходит в буфер, — ровно он, до знака. */
  text: string;
}

/** Исход последнего копирования и текст, к которому он относится. */
interface Copying {
  text: string;
  outcome: 'copied' | 'failed';
}

/**
 * Текст для копирования: моноширинный блок с подписью и кнопкой, которая кладёт его
 * в буфер обмена.
 *
 * Строки переносятся, а не прокручиваются вбок: у прокручиваемой области своя остановка
 * табом и своё имя (`docs/notes/ui.md`, «Прокручиваемая область без `tabindex`
 * недостижима с клавиатуры»), а перенос меняет только вид — в буфер уходит та же одна
 * строка. Переносится по любому месту: в адресе и токене пробелов нет, и без этого
 * длинная строка раздвигала бы страницу.
 *
 * Исход копирования остаётся до следующего нажатия, а не гаснет по таймеру: отметку,
 * которую человек не успел увидеть, ничем не отличить от её отсутствия (как у
 * `Receipt`). Исход привязан к тексту: сменился текст — отметка о прежнем гаснет, иначе
 * «скопировано» стояло бы у того, чего в буфере нет.
 */
export function CopyBlock({ label, caption, text }: CopyBlockProps) {
  const [copying, setCopying] = useState<Copying | null>(null);
  const { t } = useTranslation('ui');

  const outcome = copying?.text === text ? copying.outcome : null;
  const copied = outcome === 'copied';

  async function copy() {
    try {
      // На незащищённой странице `navigator.clipboard` нет вовсе: это тот же отказ.
      if (navigator.clipboard === undefined) throw new Error('Clipboard is not available');
      await navigator.clipboard.writeText(text);
      setCopying({ text, outcome: 'copied' });
    } catch {
      setCopying({ text, outcome: 'failed' });
    }
  }

  return (
    /*
     * Сетка, а не строка-обёртка над подписью и кнопкой: `figcaption` обязан быть прямым
     * потомком `figure` — первым или последним, — иначе он не даёт блоку имени, и
     * блок не находится по подписи ни диктором, ни тестом. Подпись и кнопка поэтому
     * стоят двумя ячейками первого ряда, а общая полоса под ними собрана их фоном.
     */
    <figure className="grid min-w-0 grid-cols-[minmax(0,1fr)_auto] overflow-hidden rounded-control border border-line bg-surface">
      <figcaption className="flex items-center border-b border-line bg-sunken py-1 pl-3 text-meta break-words text-muted">
        {caption}
      </figcaption>
      <div className="flex items-center border-b border-line bg-sunken py-1 pr-1 pl-2">
        <Button
          tone="quiet"
          className="px-2 py-1 text-meta"
          // Имя содержит видимую подпись целиком: голосовое управление находит кнопку
          // по тому, что на ней написано.
          aria-label={
            copied ? t('copyBlock.copiedLabel', { label }) : t('copyBlock.label', { label })
          }
          onClick={() => void copy()}
        >
          {copied ? (
            <Check className="size-(--ui-mark)" aria-hidden="true" />
          ) : (
            <Copy className="size-(--ui-mark)" aria-hidden="true" />
          )}
          {copied ? t('copyBlock.copied') : t('copyBlock.action')}
        </Button>
      </div>

      {/* Отказ сказан словами и на виду: браузер открывает буфер только защищённой
          странице, и молча не скопированный фрагмент человек вставил бы старым. */}
      {outcome === 'failed' ? (
        <p
          className="col-span-2 border-b border-danger-line bg-danger-soft px-3 py-1 text-meta text-danger"
          role="alert"
        >
          {t('copyBlock.failed')}
        </p>
      ) : null}

      <pre className="col-span-2 px-3 py-2 text-meta whitespace-pre-wrap text-text wrap-anywhere">
        <code>{text}</code>
      </pre>

      {/* Удача объявляется вежливо: фокус остаётся на кнопке, и смену её имени
          программа чтения с экрана произносит не всегда. */}
      <span className="sr-only" role="status">
        {copied ? t('copyBlock.done', { label }) : ''}
      </span>
    </figure>
  );
}
