import { useId, useState, type FormEvent, type RefObject } from 'react';
import { useTranslation } from 'react-i18next';
import { descriptionTooLong, type ProjectDetail } from '@/entities/project';
import { complainsAbout, errorMessage } from '@/shared/errors';
import { Button, Callout, Dialog, Input } from '@/shared/ui';
import { useUpdateProject } from '../model/use-project-actions';
import { DescriptionField } from './description-field';

/**
 * Окно «Изменить» проекта: название и описание (`UI-175`). Ключа в окне нет вовсе: он
 * неизменяем, и поле, которое нельзя править, — шум.
 *
 * Своей кнопки у окна нет: его открывает пункт меню «⋯» в шапке экрана (`ProjectMenu`,
 * TRK-618), и после закрытия фокус возвращается на «⋯» (`returnFocus`).
 */
export function EditProject({
  project,
  open,
  onOpenChange,
  returnFocus,
}: {
  project: ProjectDetail;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  returnFocus: RefObject<HTMLElement | null>;
}) {
  const { t } = useTranslation('project');

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={t('edit.title', { key: project.key })}
      description={t('edit.intro')}
      closeLabel={t('close')}
      returnFocus={returnFocus}
    >
      <EditProjectForm project={project} onDone={() => onOpenChange(false)} />
    </Dialog>
  );
}

function EditProjectForm({ project, onDone }: { project: ProjectDetail; onDone: () => void }) {
  const [title, setTitle] = useState(project.title);
  const [description, setDescription] = useState(project.description);
  const [emptyTitle, setEmptyTitle] = useState(false);
  const update = useUpdateProject();
  const titleId = useId();
  const { t } = useTranslation('project');

  const tooLong = descriptionTooLong(description);
  const badTitle = complainsAbout(update.error, 'title');

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (title.trim() === '') {
      setEmptyTitle(true);
      return;
    }
    if (tooLong) return;
    update.mutate(
      { key: project.key, title: title.trim(), description: description.trim() },
      { onSuccess: onDone },
    );
  }

  return (
    <form className="flex flex-col gap-4" onSubmit={submit} noValidate>
      <div className="flex flex-col gap-1">
        <label className="text-meta text-muted" htmlFor={titleId}>
          {t('edit.titleLabel')}
        </label>
        <Input
          id={titleId}
          value={title}
          onChange={(event) => {
            setTitle(event.target.value);
            setEmptyTitle(false);
          }}
          autoComplete="off"
          aria-invalid={emptyTitle || badTitle}
        />
        {emptyTitle ? (
          <span className="text-meta text-danger" role="alert">
            {t('edit.titleEmpty')}
          </span>
        ) : null}
      </div>

      <DescriptionField value={description} onChange={setDescription} />

      <div className="flex flex-wrap gap-2">
        <Button type="submit" disabled={update.isPending || tooLong}>
          {update.isPending ? t('edit.pending') : t('edit.submit')}
        </Button>
        <Button tone="quiet" onClick={onDone}>
          {t('cancel')}
        </Button>
      </div>

      {update.isError ? <Callout tone="danger">{errorMessage(update.error)}</Callout> : null}
    </form>
  );
}
