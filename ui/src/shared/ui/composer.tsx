import { useEffect, useId, useState, type ReactNode, type FormEvent, type MouseEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { EMPTY_DRAFT, clearDraft, readDraft, saveDraft, type Draft } from '@/shared/lib';
import { Button } from './button';
import { Callout } from './callout';
import { Dialog } from './dialog';
import { Markdown } from './markdown';

interface ComposerProps {
  /** Метка формы для программы чтения с экрана: «Ответ на DEMO-1#7», «Замечание к DEMO-1». */
  label: string;
  /** Подпись поля: «Ответ», «Замечание». */
  fieldLabel: string;
  /** Ключ черновика в `sessionStorage`: одна форма — один черновик. */
  storageKey: string;
  submitLabel: string;
  pendingLabel: string;
  /** Чем упрекнуть за пустое поле. У ответа и у замечания причина разная. */
  emptyProblem: string;
  placeholder?: string;
  /** Замечание бэкенда к полю `body`, если оно пришло. */
  problem?: string;
  isPending?: boolean;
  /** Отказ отправки словами: рисуется под кнопками и ничего не сдвигает. */
  failure?: ReactNode;
  /**
   * Отправка началась. Зовётся **до** запроса и синхронно: вызывающий обязан успеть
   * закрепить то, что может исчезнуть, раньше, чем перечитывание это уберёт.
   */
  onBegin?: () => void;
  /**
   * Отправить. `true` означает «запись подшита»: черновик стирается, поле пустеет.
   * Ключ повтора приходит сюда, а не рождается у вызывающего: он часть черновика и
   * обязан пережить провал попытки.
   */
  onSubmit: (body: string, idempotencyKey: string) => Promise<boolean>;
  /**
   * Отменить: свернуть форму и выбросить черновик. Без него кнопки «Отмена» нет —
   * форма ответа пока сама решает, показывать ли свою (`UI-142`). Composer вызывает
   * его уже после того, как черновик стёрт: вызывающему остаётся только свернуть
   * форму, а не помнить о хранилище сеанса.
   */
  onCancel?: () => void;
}

/** Подпись поля и предпросмотра: она объясняет содержание, а не несёт его. */
const LABEL = 'text-meta text-muted';

/**
 * Форма записи в дело: поле markdown, предпросмотр, черновик и упрёк за пустоту.
 *
 * Одна на все формы человека (`../docs/CONCEPT.md`, 3.4): ответ на вопрос и
 * замечание к задаче отличаются подписями, адресом отправки и последствиями, но не
 * тем, как устроен ввод. Второй экземпляр этой формы рядом означал бы два места, где
 * чинить черновик, предпросмотр и порядок элементов.
 *
 * Порядок элементов — не оформление, а требование: всё, что может появиться и
 * исчезнуть (упрёк, предпросмотр, отказ), стоит **ниже** кнопок. Растёт только то,
 * что под ними, и кнопка отправки не сдвигается ни на пиксель ни в одном состоянии
 * формы — прямо из-под пальца человека, который сейчас нажмёт ещё раз
 * (`docs/notes/ui.md`).
 */
export function Composer({
  label,
  fieldLabel,
  storageKey,
  submitLabel,
  pendingLabel,
  emptyProblem,
  placeholder,
  problem,
  isPending = false,
  failure,
  onBegin,
  onSubmit,
  onCancel,
}: ComposerProps) {
  const [draft, setDraft] = useState<Draft>(() => readDraft(storageKey));
  const [showPreview, setShowPreview] = useState(false);
  const [emptyBody, setEmptyBody] = useState(false);
  const [confirmDiscard, setConfirmDiscard] = useState(false);
  const bodyId = useId();
  const { t } = useTranslation('ui');

  // Форма может пережить смену того, о чём она: соседний вопрос той же задачи меняет
  // ключ черновика, не перемонтируя компонент.
  useEffect(() => {
    setDraft(readDraft(storageKey));
    setEmptyBody(false);
  }, [storageKey]);

  function change(changes: Partial<Draft>) {
    const next = { ...draft, ...changes };
    setDraft(next);
    saveDraft(storageKey, next);

    // Упрёк снимается первым же введённым символом. Сообщение, висящее над полем,
    // в которое человек уже пишет, — это не подсказка, а штраф за прошлое: он
    // сделал ровно то, о чём его попросили, и продолжает видеть красное.
    if (emptyBody && next.body.trim() !== '') setEmptyBody(false);
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (draft.body.trim() === '') {
      setEmptyBody(true);
      return;
    }
    setEmptyBody(false);

    // Ключ повтора рождается на первой попытке и переживает её провал: повторная
    // отправка того же черновика идёт с тем же ключом и не заводит вторую запись.
    const idempotencyKey = draft.idempotencyKey === '' ? crypto.randomUUID() : draft.idempotencyKey;
    if (draft.idempotencyKey === '') change({ idempotencyKey });

    const body = draft.body.trim();
    // Раньше запроса и синхронно: дальше начинается гонка кадра потока с ответом
    // сервера, и к её началу закреплять уже поздно.
    onBegin?.();

    if (await onSubmit(body, idempotencyKey)) {
      clearDraft(storageKey);
      setDraft(EMPTY_DRAFT);
      setShowPreview(false);
    }
  }

  /**
   * Пустой черновик не жалко: сворачиваем сразу, без вопроса — упрёк за нажатие
   * кнопки, ничего не отменяющей, был бы штрафом на пустом месте. Непустой сперва
   * спрашивает подтверждения: сообщением этого окна, а не браузерным `confirm`,
   * который не красится темой и не проходит `axe` этого проекта.
   *
   * Кнопка сама стоит `Dialog.Trigger` (`trigger`, ниже): её клик Radix и так открыл
   * бы окно. Пустой черновик эту открывалку гасит `preventDefault` — иначе окно
   * мигнуло бы вопросом, на который нечего отвечать (`UI-178`).
   */
  function requestCancel(event: MouseEvent<HTMLButtonElement>) {
    if (draft.body.trim() === '') {
      event.preventDefault();
      clearDraft(storageKey);
      onCancel?.();
    }
  }

  function discardAndCancel() {
    clearDraft(storageKey);
    setDraft(EMPTY_DRAFT);
    setShowPreview(false);
    setConfirmDiscard(false);
    onCancel?.();
  }

  const shown = emptyBody ? emptyProblem : problem;

  return (
    <form
      className="flex flex-col gap-3"
      onSubmit={(event) => void submit(event)}
      aria-label={label}
    >
      <div className="flex flex-col gap-1">
        <label className={LABEL} htmlFor={bodyId}>
          {fieldLabel}
        </label>
        <textarea
          id={bodyId}
          className="resize-y rounded-mark border border-line-strong bg-surface px-3 py-2 font-mono text-meta text-text aria-invalid:border-danger"
          value={draft.body}
          onChange={(event) => change({ body: event.target.value })}
          rows={5}
          placeholder={placeholder}
          aria-invalid={shown !== undefined}
          aria-describedby={shown === undefined ? undefined : `${bodyId}-problem`}
        />
      </div>

      <div className="flex flex-wrap gap-2">
        <Button type="submit" disabled={isPending}>
          {isPending ? pendingLabel : submitLabel}
        </Button>
        <Button tone="quiet" onClick={() => setShowPreview(!showPreview)}>
          {showPreview ? t('composer.hidePreview') : t('composer.preview')}
        </Button>
        {/* Тон `quiet`, тот же, что у «Предпросмотра»: отмена второстепенна рядом с
            отправкой, но не спрятана — найти путь назад должно быть так же просто,
            как скрыть предпросмотр.

            Кнопка сама стоит `Dialog.Trigger` (`trigger`): окно вопроса рождается
            прямо здесь, на её месте в ряду, а не отдельным узлом после формы — иначе
            Radix возвращать фокус после `Esc`/«Продолжить писать» было бы некуда, и
            он падал на `body` (`UI-175#11`, `UI-178`). Щелчок по кнопке физически
            остаётся внутри `<form>`, но её роль от этого не меняется: `type="button"`
            не даёт ей отправить форму, а содержимое окна (`children` ниже) всё равно
            уносится порталом и в разметку формы не попадает. Роль `alertdialog` —
            окно спрашивает о необратимом, программе чтения с экрана положено сказать
            это явно (`UI-142`: замена браузерному `confirm`, который не красится
            темой). */}
        {onCancel === undefined ? null : (
          <Dialog
            alert
            open={confirmDiscard}
            onOpenChange={setConfirmDiscard}
            title={t('composer.discardTitle')}
            description={t('composer.discardDescription')}
            closeLabel={t('composer.close')}
            trigger={
              <Button type="button" tone="quiet" onClick={requestCancel}>
                {t('composer.cancel')}
              </Button>
            }
          >
            <div className="flex flex-wrap gap-2">
              <Button type="button" onClick={discardAndCancel}>
                {t('composer.discardConfirm')}
              </Button>
              <Button type="button" tone="quiet" onClick={() => setConfirmDiscard(false)}>
                {t('composer.keepWriting')}
              </Button>
            </div>
          </Dialog>
        )}
      </div>

      {/* Упрёк не отрывается от поля: связь держит `aria-describedby`, а глазами он
          читается там, где человек только что нажал.

          Места под него не резервируется: упрёк стоит под кнопками, его появление
          растит форму вниз и ничего не сдвигает. Резервирование пробовалось и
          оказалось хуже — строка, зарезервированная под одну строку текста, всё равно
          двигала кнопку на 3 px (замерено сквозным тестом), а под две занимала бы
          48 пикселей в форме, где обычно упрекать не за что. */}
      {shown === undefined ? null : (
        <span className="text-meta text-danger" id={`${bodyId}-problem`} role="alert">
          {shown}
        </span>
      )}

      {showPreview && draft.body.trim() !== '' ? (
        <div className="flex flex-col gap-1 rounded-mark border border-dashed border-line-strong p-3">
          <span className={LABEL}>{t('composer.agentView')}</span>
          <Markdown>{draft.body}</Markdown>
        </div>
      ) : null}

      {failure === undefined ? null : <Callout tone="danger">{failure}</Callout>}
    </form>
  );
}
