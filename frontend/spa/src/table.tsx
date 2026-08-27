// One table renderer for the whole dashboard.
//
// Below 700px the stylesheet hides <thead> and turns each <td> into a two
// column card whose label comes from `td::before { content: attr(data-label) }`.
// That only works if every cell carries data-label, and hand-written tables
// kept forgetting: Compare and Generated omitted it entirely, so those rows
// collapsed into unlabelled cell soup on a phone. Driving the markup from a
// column list makes the label structural -- it is the same string as the header,
// so it cannot drift -- and forces the .table-wrap scroll container and the
// caption that all nine tables were missing.

import type { ReactNode } from "react";

export interface Column<T> {
  /** Stable key for React and for the cell's data-label. */
  key: string;
  /** Column heading, also used as the mobile card label. */
  header: string;
  cell: (row: T) => ReactNode;
  /** Class for the <td>, e.g. "mono" or "truncate". */
  className?: string;
  /** Overrides the mobile label when the header is not the right wording. */
  label?: string;
}

export function DataTable<T>({
  caption,
  columns,
  rows,
  rowKey,
  rowTestId,
  empty = "Nothing to show.",
}: {
  /** Describes the table for screen readers; visually hidden. */
  caption: string;
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T, index: number) => string;
  rowTestId?: string;
  empty?: ReactNode;
}) {
  if (!rows.length) return <p className="quiet">{empty}</p>;

  return (
    <div className="table-wrap">
      <table>
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column.key} scope="col">
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={rowKey(row, index)} data-testid={rowTestId}>
              {columns.map((column) => (
                <td
                  key={column.key}
                  className={column.className}
                  data-label={column.label ?? column.header}
                >
                  {column.cell(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
