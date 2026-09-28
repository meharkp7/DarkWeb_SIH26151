import type { ReactNode } from 'react';

export interface Column<T> {
  /** Stable key for the column. */
  readonly key: string;
  readonly header: string;
  readonly render: (row: T) => ReactNode;
  readonly align?: 'start' | 'end';
  readonly width?: string;
}

export interface DataTableProps<T> {
  readonly columns: ReadonlyArray<Column<T>>;
  readonly rows: readonly T[];
  readonly rowKey: (row: T) => string;
  /** Table caption read by assistive tech (also shown subtly). */
  readonly caption?: string;
  /** Rendered inside a full-width cell when there are no rows. */
  readonly empty?: ReactNode;
  /** Row class hook, e.g. for highlighting. */
  readonly rowClassName?: (row: T) => string | undefined;
}

/** Dense, accessible data table used by every list screen. */
export function DataTable<T>({
  columns,
  rows,
  rowKey,
  caption,
  empty,
  rowClassName,
}: DataTableProps<T>) {
  return (
    <div className="table-wrap">
      <table className="data-table">
        {caption !== undefined && <caption className="data-table__caption">{caption}</caption>}
        <thead>
          <tr>
            {columns.map((column) => (
              <th
                key={column.key}
                scope="col"
                style={{
                  textAlign: column.align ?? 'start',
                  width: column.width,
                }}
              >
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td colSpan={columns.length} className="data-table__empty">
                {empty ?? 'No records.'}
              </td>
            </tr>
          ) : (
            rows.map((row) => (
              <tr key={rowKey(row)} className={rowClassName?.(row)}>
                {columns.map((column) => (
                  <td key={column.key} style={{ textAlign: column.align ?? 'start' }}>
                    {column.render(row)}
                  </td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}
