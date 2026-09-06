import type { LiveStatus as LiveStatusValue } from '../model/use-live-journal';
import styles from './live-status.module.css';

/**
 * Как называется каждое состояние потока и что оно значит для человека.
 *
 * Перечислено ключами объекта: состояние, добавленное в `LiveStatus`, роняет сборку,
 * а не остаётся без подписи (тот же приём, что у тонов и списков контракта).
 */
const STATES = {
  connecting: {
    label: 'подключаемся',
    title: 'Открываем живой поток журнала',
    alarming: false,
  },
  live: {
    label: 'на связи',
    title: 'Живой поток журнала открыт: экран обновляется сам',
    alarming: false,
  },
  reconnecting: {
    label: 'нет связи',
    title: 'Соединение с потоком журнала потеряно, идёт переподключение',
    alarming: true,
  },
} satisfies Record<LiveStatusValue, { label: string; title: string; alarming: boolean }>;

/**
 * Состояние живого потока в шапке: свежесть того, на что человек смотрит
 * (`CONCEPT.md`, 5).
 *
 * Первое открытие не красное. Красный означает «показанному больше нельзя верить»,
 * и вспыхивать им на каждой загрузке страницы значит обесценить его к третьему разу.
 */
export function LiveStatus({ status }: { status: LiveStatusValue }) {
  const state = STATES[status];

  return (
    <span
      className={state.alarming ? styles.lost : styles.connected}
      role="status"
      title={state.title}
    >
      {state.label}
    </span>
  );
}
