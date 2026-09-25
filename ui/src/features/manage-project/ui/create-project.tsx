import { useId, useState, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router';
import { Plus } from 'lucide-react';
import { descriptionTooLong } from '@/entities/project';
import { complainsAbout, errorMessage } from '@/shared/errors';
import { projectHref } from '@/shared/lib';
import { Button, Callout, Dialog, Input } from '@/shared/ui';
import { useCreateProject } from '../model/use-project-actions';
import { DescriptionField } from './description-field';

/**
 * Кнопка «Новый проект» и её окно: ключ, название, описание (`UI-175`, решение 8
 * `TRK-150`). Показывать её или нет, решает место вызова — по набору ключа
 * (`useProjectRights`), окно само прав не проверяет.
 *
 * Заведённый проект открывается сразу: человек заводит его, чтобы вести, и первым
 * делом ему нужен экран проекта, а не та же панель со строкой ниже.
 */
export function CreateProject({ onCreated }: { onCreated?: () => void }) {
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();
  const { t } = useTranslation('project');

  return (
    <Dialog
      open={open}
      onOpenChange={setOpen}
      title={t('create.title')}
      description={t('create.intro')}
      closeLabel={t('close')}
      trigger={
        <Button tone="quiet" size="sm">
          <Plus className="size-(--ui-mark)" aria-hidden="true" />
          {t('create.open')}
        </Button>
      }
    >
      <CreateProjectForm
        onCancel={() => setOpen(false)}
        onCreated={(key) => {
          setOpen(false);
          void navigate(projectHref(key));
          onCreated?.();
        }}
      />
    </Dialog>
  );
}

/**
 * Форма окна. Живёт внутри содержимого окна и потому рождается заново при каждом
 * открытии: прошлый отказ и прошлый набор в новое окно не переезжают.
 */
function CreateProjectForm({
  onCancel,
  onCreated,
}: {
  onCancel: () => void;
  onCreated: (key: string) => void;
}) {
  const [key, setKey] = useState('');
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [problem, setProblem] = useState<'key' | 'title' | null>(null);
  const create = useCreateProject();
  const keyId = useId();
  const keyHintId = useId();
  const titleId = useId();
  const { t } = useTranslation('project');

  const badKey = complainsAbout(create.error, 'key');
  const badTitle = complainsAbout(create.error, 'title');
  const tooLong = descriptionTooLong(description);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (key.trim() === '') {
      setProblem('key');
      return;
    }
    if (title.trim() === '') {
      setProblem('title');
      return;
    }
    if (tooLong) return;
    setProblem(null);

    create.mutate(
      { key: key.trim(), title: title.trim(), description: description.trim() },
      { onSuccess: (project) => onCreated(project.key) },
    );
  }

  return (
    <form className="flex flex-col gap-4" onSubmit={submit} noValidate>
      <div className="flex flex-col gap-1">
        <label className="text-meta text-muted" htmlFor={keyId}>
          {t('create.keyLabel')}
        </label>
        {/* Ключ — идентификатор контракта: моноширинным, без автоподстановок
            клавиатуры телефона. Образец назван подсказкой, а проверяет его бэкенд. */}
        <Input
          id={keyId}
          className="font-mono"
          value={key}
          onChange={(event) => {
            setKey(event.target.value);
            setProblem(null);
          }}
          autoComplete="off"
          autoCapitalize="characters"
          spellCheck={false}
          aria-invalid={problem === 'key' || badKey}
          aria-describedby={keyHintId}
        />
        <span className="text-meta text-muted" id={keyHintId}>
          {t('create.keyHint')}
        </span>
        {problem === 'key' ? (
          <span className="text-meta text-danger" role="alert">
            {t('create.keyEmpty')}
          </span>
        ) : null}
      </div>

      <div className="flex flex-col gap-1">
        <label className="text-meta text-muted" htmlFor={titleId}>
          {t('create.titleLabel')}
        </label>
        <Input
          id={titleId}
          value={title}
          onChange={(event) => {
            setTitle(event.target.value);
            setProblem(null);
          }}
          autoComplete="off"
          aria-invalid={problem === 'title' || badTitle}
        />
        {problem === 'title' ? (
          <span className="text-meta text-danger" role="alert">
            {t('create.titleEmpty')}
          </span>
        ) : null}
      </div>

      <DescriptionField value={description} onChange={setDescription} />

      {/* Кнопки выше всего изменчивого: отказ, выросший над ними, увёл бы их
          из-под пальца (`docs/notes/ui.md`). */}
      <div className="flex flex-wrap gap-2">
        <Button type="submit" disabled={create.isPending || tooLong}>
          {create.isPending ? t('create.pending') : t('create.submit')}
        </Button>
        <Button tone="quiet" onClick={onCancel}>
          {t('cancel')}
        </Button>
      </div>

      {create.isError ? (
        <Callout tone="danger">
          {errorMessage(create.error)} {badKey ? t('create.keyHint') : t('retrySafe')}
        </Callout>
      ) : null}
    </form>
  );
}
