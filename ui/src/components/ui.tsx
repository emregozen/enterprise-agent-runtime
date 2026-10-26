import {
  flexRender,
  getCoreRowModel,
  getFilteredRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  useReactTable,
  type ColumnDef,
  type SortingState,
} from "@tanstack/react-table";
import { Sparkles } from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { copy } from "../lib/copy";
import { statusLabel } from "../lib/format";
import { codeTokens } from "../lib/highlight";

export function Badge({ status }: { status: string }) {
  const tone = status === "succeeded" || status === "published" ? "ok"
    : status === "failed" || status === "deleted" ? "bad"
    : status === "needs_review" || status === "paused" ? "warn"
    : status === "running" || status === "pending" ? "info" : "";
  return <span className={`badge ${tone}`}>{statusLabel(status)}</span>;
}

export function Modal({ title, children, onClose }: { title: string; children: ReactNode; onClose: () => void }) {
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="modal-back" role="presentation" onMouseDown={onClose}>
      <div className="modal" role="dialog" aria-modal="true" aria-label={title} onMouseDown={(event) => event.stopPropagation()}>
        <h2>{title}</h2>
        {children}
      </div>
    </div>
  );
}

export function Empty({ title, body, action }: { title: string; body: string; action?: ReactNode }) {
  return (
    <div className="empty">
      <div className="empty-mark" aria-hidden><Sparkles size={22} /></div>
      <strong>{title}</strong>
      <p>{body}</p>
      {action}
    </div>
  );
}

export function SkeletonRows() {
  return (
    <div className="card" aria-busy="true" aria-label={copy.loading}>
      <div className="skeleton" />
      <div className="skeleton" style={{ marginTop: 10, width: "70%" }} />
      <div className="skeleton" style={{ marginTop: 10, width: "40%" }} />
    </div>
  );
}

export function DataTable<T>({
  data,
  columns,
  search,
}: {
  data: T[];
  columns: ColumnDef<T, unknown>[];
  search?: string;
}) {
  const [sorting, setSorting] = useState<SortingState>([]);
  const table = useReactTable({
    data,
    columns,
    state: { sorting, globalFilter: search ?? "" },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    initialState: { pagination: { pageSize: 8 } },
  });
  const rows = table.getRowModel().rows;
  return (
    <div>
      <div className="table-wrap">
        <table className="data">
          <thead>
            {table.getHeaderGroups().map((group) => (
              <tr key={group.id}>
                {group.headers.map((header) => (
                  <th key={header.id}>
                    {header.isPlaceholder ? null : (
                      <button type="button" onClick={header.column.getToggleSortingHandler()}>
                        {flexRender(header.column.columnDef.header, header.getContext())}
                        {header.column.getIsSorted() === "asc" ? " ↑" : header.column.getIsSorted() === "desc" ? " ↓" : ""}
                      </button>
                    )}
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr>
                <td colSpan={columns.length}>{copy.none}</td>
              </tr>
            )}
            {rows.map((row) => (
              <tr key={row.id}>
                {row.getVisibleCells().map((cell) => (
                  <td key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="pager">
        <span>{copy.records(table.getFilteredRowModel().rows.length)}</span>
        <span className="row">
          <button className="btn-ghost" type="button" onClick={() => table.previousPage()} disabled={!table.getCanPreviousPage()}>{copy.previous}</button>
          <button className="btn-ghost" type="button" onClick={() => table.nextPage()} disabled={!table.getCanNextPage()}>{copy.next}</button>
        </span>
      </div>
    </div>
  );
}

export function useSearch<T>(rows: T[], pick: (row: T) => string, query: string): T[] {
  return useMemo(() => {
    const needle = query.trim().toLocaleLowerCase("tr");
    if (!needle) return rows;
    return rows.filter((row) => pick(row).toLocaleLowerCase("tr").includes(needle));
  }, [rows, pick, query]);
}

export function CodeBlock({ code }: { code: string }) {
  return (
    <pre className="code">
      {codeTokens(code).map((token, index) =>
        token.kind === "text" ? token.text : <span key={index} className={`tok-${token.kind}`}>{token.text}</span>,
      )}
    </pre>
  );
}

export function Markdown({ text }: { text: string }) {
  const blocks = text.split(/\n{2,}/);
  return (
    <div className="md">
      {blocks.map((block, index) => {
        if (block.startsWith("|")) {
          const lines = block.split("\n").filter((line) => !line.includes("---"));
          return (
            <table key={index}>
              <tbody>
                {lines.map((line) => (
                  <tr key={line}>
                    {line.split("|").filter((cell) => cell.trim() !== "").map((cell) => <td key={cell}>{cell.trim()}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          );
        }
        if (block.startsWith("# ")) return <h2 key={index}>{block.slice(2)}</h2>;
        if (block.startsWith("## ")) return <h3 key={index}>{block.slice(3)}</h3>;
        return <p key={index} dangerouslySetInnerHTML={{ __html: block.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>").replace(/\n/g, "<br/>") }} />;
      })}
    </div>
  );
}

export function Toast({ message }: { message: string }) {
  if (!message) return null;
  return <div className="toasts" role="status"><div className="toast">{message}</div></div>;
}
