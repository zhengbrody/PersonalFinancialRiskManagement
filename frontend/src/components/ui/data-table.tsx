"use client";

/**
 * Generic data table for the Risk cockpit — one component behind the factor
 * beta / component VaR / stress / liquidity tables (DRY). Features: sticky
 * header, optional ticker search/filter, click-to-sort columns (numeric or
 * string), and top-N collapse with a "show all" toggle. Sorting/filtering are
 * memoised so re-renders (tab/filter changes elsewhere) stay cheap.
 */

import { useMemo, useState } from "react";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

export type Column<T> = {
  key: string;
  header: string;
  align?: "left" | "right";
  render: (row: T) => React.ReactNode;
  /** Provide to make the column sortable. */
  sortValue?: (row: T) => number | string;
  /** Optional per-cell className (e.g. heat background). */
  cellClassName?: (row: T) => string;
};

export function DataTable<T>({
  rows,
  columns,
  rowKey,
  filterKey,
  filterPlaceholder = "Filter ticker…",
  initialSort,
  topN = 10,
  minWidth = 460,
  emptyText = "No rows.",
}: {
  rows: T[];
  columns: Column<T>[];
  rowKey: (row: T) => string;
  /** Field to filter on via the search box (omit to hide the box). */
  filterKey?: keyof T;
  filterPlaceholder?: string;
  initialSort?: { key: string; dir: "asc" | "desc" };
  topN?: number;
  minWidth?: number;
  emptyText?: string;
}) {
  const [sortKey, setSortKey] = useState<string | null>(initialSort?.key ?? null);
  const [dir, setDir] = useState<"asc" | "desc">(initialSort?.dir ?? "desc");
  const [query, setQuery] = useState("");
  const [expanded, setExpanded] = useState(false);

  const processed = useMemo(() => {
    let r = rows;
    if (filterKey && query.trim()) {
      const q = query.trim().toLowerCase();
      r = r.filter((row) => String(row[filterKey] ?? "").toLowerCase().includes(q));
    }
    const col = sortKey ? columns.find((c) => c.key === sortKey) : undefined;
    if (col?.sortValue) {
      const sv = col.sortValue;
      r = [...r].sort((a, b) => {
        const av = sv(a);
        const bv = sv(b);
        const cmp =
          typeof av === "number" && typeof bv === "number"
            ? av - bv
            : String(av).localeCompare(String(bv));
        return dir === "asc" ? cmp : -cmp;
      });
    }
    return r;
  }, [rows, columns, filterKey, query, sortKey, dir]);

  const shown = expanded ? processed : processed.slice(0, topN);
  const hidden = processed.length - shown.length;

  function onSort(col: Column<T>) {
    if (!col.sortValue) return;
    if (sortKey === col.key) {
      setDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(col.key);
      setDir("desc");
    }
  }

  return (
    <div className="space-y-2">
      {filterKey && rows.length > topN && (
        <Input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={filterPlaceholder}
          className="h-8 max-w-[12rem] text-xs"
          aria-label={filterPlaceholder}
        />
      )}
      <div className="max-h-[28rem] overflow-auto rounded-md border border-border">
        <table className="w-full text-xs" style={{ minWidth }}>
          <thead className="sticky top-0 z-10 bg-card">
            <tr className="border-b border-border text-left text-muted-foreground">
              {columns.map((c) => {
                const sortable = Boolean(c.sortValue);
                const activeSort = sortKey === c.key;
                return (
                  <th
                    key={c.key}
                    className={cn(
                      "px-3 py-2 text-[10px] font-medium uppercase tracking-wider",
                      c.align === "right" && "text-right",
                      sortable && "cursor-pointer select-none hover:text-foreground",
                    )}
                    onClick={() => onSort(c)}
                    aria-sort={activeSort ? (dir === "asc" ? "ascending" : "descending") : undefined}
                  >
                    {c.header}
                    {sortable && (
                      <span className="ml-1 text-[9px] opacity-60">
                        {activeSort ? (dir === "asc" ? "▲" : "▼") : "↕"}
                      </span>
                    )}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody className="font-mono">
            {shown.length === 0 ? (
              <tr>
                <td colSpan={columns.length} className="px-3 py-4 text-center font-sans text-muted-foreground">
                  {emptyText}
                </td>
              </tr>
            ) : (
              shown.map((row) => (
                <tr
                  key={rowKey(row)}
                  className="border-b border-border/40 transition-colors hover:bg-muted/40"
                >
                  {columns.map((c) => (
                    <td
                      key={c.key}
                      className={cn(
                        "px-3 py-1.5",
                        c.align === "right" && "text-right",
                        c.cellClassName?.(row),
                      )}
                    >
                      {c.render(row)}
                    </td>
                  ))}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
      {hidden > 0 && !expanded && (
        <button
          type="button"
          onClick={() => setExpanded(true)}
          className="text-xs text-primary hover:underline"
        >
          Show all {processed.length}
        </button>
      )}
      {expanded && processed.length > topN && (
        <button
          type="button"
          onClick={() => setExpanded(false)}
          className="text-xs text-primary hover:underline"
        >
          Show top {topN}
        </button>
      )}
    </div>
  );
}
