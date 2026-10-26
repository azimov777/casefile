import { useId, useState, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { errorMessage } from '@/shared/errors';
import { Button, Callout, Dialog, Select } from '@/shared/ui';
import { useUploadFile } from '../model/use-file-actions';
import { FileField } from './file-field';

/** Проект, в который можно положить файл: живой, не архивный. */
export interface UploadTarget {
  key: string;
  title: string;
}

/**
 * Окно «Загрузить файл»: проект, файл и необязательное имя. Файл остаётся в проекте до
 * удаления (TRK/files#3). Архивные проекты в выборе не показываются: заморожены, и сервер
 * ответил бы `project_archived` (TRK/ui-screens#2).
 *
 * Своя кнопка и своё состояние открытия, как у окон «Люди» (`UI-175`, `UI-178`).
 */
export function UploadDialog({
  projects,
  ready,
  defaultProject,
  onUploaded,
}: {
  projects: UploadTarget[];
  /** Проекты прочитаны: пока нет, кнопка заперта, а «проектов нет» не говорится о неизвестном. */
  ready: boolean;
  /** Проект, выбранный на экране отбором: загрузка по умолчанию идёт в него. */
  defaultProject: string | null;
  onUploaded?: () => void;
}) {
  const [open, setOpen] = useState(false);
  const { t } = useTranslation('files');

  return (
    <Dialog
      open={open}
      onOpenChange={setOpen}
      title={t('upload.title')}
      description={t('upload.intro')}
      closeLabel={t('close')}
      trigger={<Button disabled={!ready}>{t('upload.open')}</Button>}
    >
      <UploadForm
        projects={projects}
        defaultProject={defaultProject}
        onClose={() => setOpen(false)}
        onUploaded={onUploaded}
      />
    </Dialog>
  );
}

function UploadForm({
  projects,
  defaultProject,
  onClose,
  onUploaded,
}: {
  projects: UploadTarget[];
  defaultProject: string | null;
  onClose: () => void;
  onUploaded?: () => void;
}) {
  const upload = useUploadFile();
  const { t } = useTranslation('files');
  const first = projects.find((project) => project.key === defaultProject) ?? projects[0];
  const [chosen, setChosen] = useState<string | null>(null);
  // Выбор человека, пока он есть среди проектов; иначе — проект по умолчанию.
  const project = projects.find((item) => item.key === chosen)?.key ?? first?.key ?? '';
  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState('');
  const [missing, setMissing] = useState(false);
  const projectId = useId();
  const failed = upload.error !== null && upload.error !== undefined;

  if (first === undefined) return <Callout>{t('upload.noProjects')}</Callout>;

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (file === null) {
      setMissing(true);
      return;
    }
    setMissing(false);
    upload.mutate(
      { project, file, name: name.trim() },
      {
        onSuccess: () => {
          onUploaded?.();
          onClose();
        },
      },
    );
  }

  /*
   * Выбор проекта стоит снаружи `<form>`: Radix Select внутри формы держит скрытый родной
   * `<select>` без пунктов и на смене значения отвечает событием `change` с пустой
   * строкой — проект становился пустым, и сервер отвечал `project_not_found`.
   */
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-1">
        <span className="text-meta text-muted" id={projectId}>
          {t('upload.project')}
        </span>
        <div>
          <Select
            label={t('upload.project')}
            value={project}
            onValueChange={setChosen}
            options={projects.map((item) => ({
              value: item.key,
              label: `${item.key} — ${item.title}`,
            }))}
            className="border-line-strong bg-surface text-text"
          />
        </div>
      </div>

      <form className="flex flex-col gap-4" onSubmit={submit} noValidate>
        <FileField
          fileLabel={t('upload.file')}
          nameLabel={t('upload.name')}
          nameHint={t('upload.nameHint')}
          name={name}
          onName={setName}
          onFile={(next) => {
            setFile(next);
            setMissing(false);
          }}
          invalid={missing}
        />

        <div className="flex flex-wrap gap-2">
          <Button type="submit" disabled={upload.isPending}>
            {upload.isPending ? t('upload.pending') : t('upload.submit')}
          </Button>
          <Button tone="quiet" onClick={onClose}>
            {t('cancel')}
          </Button>
        </div>

        {failed ? <Callout tone="danger">{errorMessage(upload.error)}</Callout> : null}
      </form>
    </div>
  );
}
