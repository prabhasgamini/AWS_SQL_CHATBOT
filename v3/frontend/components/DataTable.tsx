"use client";

import { useState } from "react";
import type { Row } from "@/lib/types";

const PAGE = 25;

function format(value: Row[string]) {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number" && !Number.isInteger(value)) {
    return value.toLocaleString(undefined, { maximumFractionDigits: 2 });
  }
  return String(value);
}

export default function DataTable({
  columns,
  rows,
  truncated,
}: {
  columns: string[];
  rows: Row[];
  truncated?: boolean;
}) {
  const [visible, setVisible] = useState(PAGE);
  if (rows.length === 0) return null;

  const cols = columns.length ? columns : Object.keys(rows[0]);
  const isNumeric = (col: string) => typeof rows[0][col] === "number";

  return (
    <div className="overflow-hidden rounded-xl border border-line bg-panel">
      <div className="max-h-96 overflow-auto">
        <table className="w-full border-collapse text-left text-[13px]">
          <thead className="sticky top-0 bg-panel">
            <tr className="border-b border-line">
              {cols.map((col) => (
                <th
                  key={col}
                  className={`whitespace-nowrap px-3 py-2 text-xs font-semibold text-muted ${
                    isNumeric(col) ? "text-right" : ""
                  }`}
                >
                  {col}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.slice(0, visible).map((row, i) => (
              <tr key={i} className="border-b border-line/60 last:border-0 hover:bg-line/30">
                {cols.map((col) => (
                  <td
                    key={col}
                    className={`whitespace-nowrap px-3 py-1.5 font-mono text-xs ${
                      isNumeric(col) ? "text-right" : ""
                    }`}
                  >
                    {format(row[col])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="flex items-center justify-between border-t border-line px-3 py-1.5 text-xs text-muted">
        <span>
          {rows.length} row{rows.length === 1 ? "" : "s"}
          {truncated ? " (capped, more exist)" : ""}
        </span>
        {visible < rows.length && (
          <button onClick={() => setVisible((v) => v + PAGE)} className="hover:text-ink">
            Show more
          </button>
        )}
      </div>
    </div>
  );
}
