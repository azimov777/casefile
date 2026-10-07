import { useRef, useState, type RefObject } from 'react';
import { useTranslation } from 'react-i18next';
import { Archive, ArchiveRestore, Pencil } from 'lucide-react';
import type { ProjectDetail } from '@/entities/project';
import { ActionMenu, type ActionMenuItem } from '@/shared/ui';
import { ProjectArchiving } from './archive-project';
import { areaMenuActions, projectMenuActions, type MenuAction } from '../model/menu-actions';
import { AreaArchivingDialog, EditAreaDialog } from './area-dialogs';
import { EditProject } from './edit-project';

/*
 * Меню «⋯» в шапке экрана проекта и страницы области (TRK-618, решение TRK#46):
 * «Изменить» и «В архив», у архивного — только «Восстановить». Действий не прибавилось и
 * не убавилось — они переехали из строки шапки, где стояли посреди чтения.
 *
 * Окна живут здесь, рядом с меню, а не внутри него: меню закрывается выбором пункта, и
 * окно внутри закрытого меню исчезло бы вместе с ним. После окна фокус возвращается на
 * «⋯» (`returnFocus`).
 */

/** Знак пункта: тот же, что стоял на кнопке до меню. */
const ACTION_ICON = { edit: Pencil, archive: Archive, restore: ArchiveRestore } as const;

/** Какое окно меню открыто: правка, архив (или восстановление) — или никакое. */
type MenuDialog = 'edit' | 'archiving' | null;

/** Окно пункта: архив и восстановление — одно окно, чей вопрос следует за `archived_at`. */
const ACTION_DIALOG: Record<MenuAction, Exclude<MenuDialog, null>> = {
  edit: 'edit',
  archive: 'archiving',
  restore: 'archiving',
};

/** Управление одним окном меню: открыто ли, как закрыть и куда вернуть фокус. */
function dialogPlace(
  dialog: MenuDialog,
  which: Exclude<MenuDialog, null>,
  setDialog: (next: MenuDialog) => void,
  menu: RefObject<HTMLButtonElement | null>,
) {
  return {
    open: dialog === which,
    onOpenChange: (open: boolean) => setDialog(open ? which : null),
    returnFocus: menu,
  };
}

/**
 * Меню проекта. Показывать ли его вовсе, решает экран — по правам сеанса
 * (`useProjectRights().manage`).
 */
export function ProjectMenu({ project, archived }: { project: ProjectDetail; archived: boolean }) {
  const [dialog, setDialog] = useState<MenuDialog>(null);
  const menu = useRef<HTMLButtonElement>(null);
  const { t } = useTranslation('project');

  const items: ActionMenuItem[] = projectMenuActions(archived).map((action) => ({
    id: action,
    label: t(`${action}.open`),
    icon: ACTION_ICON[action],
    onSelect: () => setDialog(ACTION_DIALOG[action]),
  }));

  const editing = dialogPlace(dialog, 'edit', setDialog, menu);
  const archiving = dialogPlace(dialog, 'archiving', setDialog, menu);

  return (
    <>
      <ActionMenu ref={menu} label={t('menu.label', { key: project.key })} items={items} />
      {archived ? null : <EditProject project={project} {...editing} />}
      <ProjectArchiving projectKey={project.key} archived={archived} {...archiving} />
    </>
  );
}

/** Что меню знает об области: адрес и то, что правит окно «Изменить». */
interface MenuArea {
  address: string;
  title: string;
  description: string;
}

/**
 * Меню области. Права решает страница, пункты — `areaMenuActions`. Без пунктов
 * меню нет вовсе.
 */
export function AreaMenu({
  area,
  canEdit,
  canArchive,
  archived,
}: {
  area: MenuArea;
  canEdit: boolean;
  canArchive: boolean;
  archived: boolean;
}) {
  const [dialog, setDialog] = useState<MenuDialog>(null);
  const menu = useRef<HTMLButtonElement>(null);
  const { t } = useTranslation('area');

  const items: ActionMenuItem[] = areaMenuActions({ canEdit, canArchive, archived }).map(
    (action) => ({
      id: action,
      label: t(`${action}.open`),
      icon: ACTION_ICON[action],
      onSelect: () => setDialog(ACTION_DIALOG[action]),
    }),
  );
  if (items.length === 0) return null;

  const editing = dialogPlace(dialog, 'edit', setDialog, menu);
  const archiving = dialogPlace(dialog, 'archiving', setDialog, menu);

  return (
    <>
      <ActionMenu ref={menu} label={t('menu.label', { address: area.address })} items={items} />
      {canEdit ? <EditAreaDialog area={area} {...editing} /> : null}
      {canArchive ? (
        <AreaArchivingDialog address={area.address} archived={archived} {...archiving} />
      ) : null}
    </>
  );
}
