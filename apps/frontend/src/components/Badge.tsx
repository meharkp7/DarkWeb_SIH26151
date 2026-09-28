import type { ReactNode } from 'react';
import { cx } from '../lib/format';

export type Tone = 'neutral' | 'info' | 'ok' | 'warn' | 'danger';

export interface BadgeProps {
  readonly tone?: Tone;
  readonly title?: string;
  readonly children: ReactNode;
}

/** Compact status chip used across tables, panels and the header. */
export function Badge({ tone = 'neutral', title, children }: BadgeProps) {
  return (
    <span className={cx('badge', `badge--${tone}`)} title={title}>
      {children}
    </span>
  );
}
