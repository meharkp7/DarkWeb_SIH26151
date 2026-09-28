import { Panel } from './Panel';
import { EmptyState } from './States';
import type { ReactNode } from 'react';

export interface SectionCardProps {
  readonly title: string;
  /** Endpoint that will back this section once implemented. */
  readonly endpoint: string;
  readonly children?: ReactNode;
  /** Custom message shown when there is no live content. */
  readonly emptyMessage?: string;
}

/**
 * One section of a long-form screen (e.g. the actor profile). Renders live
 * children when the API provides data, otherwise an explicit
 * "not available via API yet" state naming the planned endpoint.
 */
export function SectionCard({ title, endpoint, children, emptyMessage }: SectionCardProps) {
  return (
    <Panel
      title={title}
      headingLevel={2}
      actions={
        <code className="endpoint-chip" title="Planned endpoint">
          {endpoint}
        </code>
      }
    >
      {children ?? (
        <EmptyState
          title={`${title}: no data`}
          message={
            emptyMessage ??
            'This section is not served by the API yet, so nothing is shown rather than inventing values.'
          }
          endpoint={endpoint}
        />
      )}
    </Panel>
  );
}
