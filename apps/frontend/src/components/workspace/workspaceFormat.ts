import type { WorkspaceEntity } from '../../api/types';

/**
 * Small shared readers for the case-workspace payload.
 *
 * Both workspace panels need the same two lookups, and both need to be
 * defensive: the workspace serializer is not guaranteed to return every field
 * the TypeScript type declares (see `WorkspaceEvidence.metadata`), so every
 * read here takes `unknown` and narrows at runtime.
 */

/** Index entities by id for O(1) surface-form resolution. */
export function indexEntities(
  entities: readonly WorkspaceEntity[],
): Map<string, WorkspaceEntity> {
  return new Map(entities.map((entity) => [entity.entity_id, entity]));
}

/** Human name for an entity id, falling back to a shortened UUID. */
export function entityLabel(byId: ReadonlyMap<string, WorkspaceEntity>, id: string): string {
  const entity = byId.get(id);
  if (entity === undefined) return id;
  return entity.surface_form === '' ? id : entity.surface_form;
}

/**
 * Pull a display title out of a free-form `metadata` bag.
 *
 * Returns `null` for a missing bag or a non-string `title` so callers can fall
 * back instead of rendering `undefined`.
 */
export function metaTitle(metadata: unknown): string | null {
  if (typeof metadata !== 'object' || metadata === null) return null;
  const title = (metadata as Record<string, unknown>).title;
  if (typeof title === 'string' && title.trim() !== '') return title;
  return null;
}

/** Parse an ISO timestamp to epoch millis, or `null` when absent/unparseable. */
export function timeOf(value: string | null | undefined): number | null {
  if (value === null || value === undefined || value === '') return null;
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? null : parsed;
}

/** "3 h 12 m" / "4 d 2 h" / "—". Human-scale collection lag. */
export function formatLag(minutes: number | null): string {
  if (minutes === null || !Number.isFinite(minutes)) return '—';
  const total = Math.max(0, Math.round(minutes));
  if (total < 60) return `${total} min`;
  if (total < 60 * 24) {
    const hours = Math.floor(total / 60);
    const rest = total % 60;
    return rest === 0 ? `${hours} h` : `${hours} h ${rest} m`;
  }
  const days = Math.floor(total / (60 * 24));
  const hours = Math.floor((total % (60 * 24)) / 60);
  return hours === 0 ? `${days} d` : `${days} d ${hours} h`;
}
