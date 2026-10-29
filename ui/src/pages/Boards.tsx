import { AlertTriangle, ArrowLeft, ArrowRight, Eye, LayoutGrid, Pencil, Plus, RefreshCw, Trash2, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ReportView } from "../components/ReportView";
import { Select } from "../components/Select";
import { ActionButton, Badge, ConfirmDialog, Empty, Modal, SkeletonRows } from "../components/ui";
import { api, ApiError } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useBusy } from "../lib/busy";
import { presentText } from "../lib/errors";
import { formatWhen } from "../lib/format";
import { announceError, notify } from "../lib/notify";

type Size = "sm" | "md" | "lg";
type WidgetDef = { id: string; agent_id: string; size: Size };
type Board = { id: string; name: string; shared: boolean; owned: boolean; widgets: WidgetDef[] };
type RunLite = { id: string; status: string; created_at: string; started_at: string | null; finished_at: string | null; error: string | null };
type Widget = {
  id: string;
  agent_id: string;
  size: Size;
  state: "ok" | "running" | "failed" | "empty" | "missing" | "no_access";
  agent_name: string | null;
  can_run?: boolean;
  active_run?: RunLite | null;
  latest_run?: RunLite | null;
  result?: (RunLite & { report_markdown: string | null }) | null;
  stale?: { run_id: string; status: string; reason: string; failed_at: string; has_older_result: boolean } | null;
};
type Snapshot = { board: Board; widgets: Widget[] };
type Agent = { id: string; name: string; status: string };

const SIZES: Size[] = ["sm", "md", "lg"];

export function Boards() {
  const [params, setParams] = useSearchParams();
  const [boards, setBoards] = useState<Board[] | null>(null);
  const [snap, setSnap] = useState<Snapshot | null>(null);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState(false);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [adding, setAdding] = useState("");
  const { run, pending } = useBusy();
  const { can } = useAuth();
  const boardId = params.get("b") || boards?.[0]?.id || "";
  const idRef = useRef(boardId);
  idRef.current = boardId;

  const loadBoards = useCallback(() => api<Board[]>("/api/boards").then(setBoards).catch((exc: ApiError) => setError(exc.message)), []);
  const loadSnapshot = useCallback(() => {
    const id = idRef.current;
    if (!id) return Promise.resolve();
    return api<Snapshot>(`/api/boards/${id}/snapshot`)
      .then((body) => { if (idRef.current === id) setSnap(body); })
      .catch((exc: ApiError) => setError(exc.message));
  }, []);

  useEffect(() => { void loadBoards(); api<Agent[]>("/api/agents").then(setAgents).catch(() => setAgents([])); }, [loadBoards]);
  useEffect(() => { setSnap(null); setEditing(false); void loadSnapshot(); }, [boardId, loadSnapshot]);

  const anyRunning = snap?.widgets.some((w) => w.state === "running") ?? false;
  useEffect(() => {
    if (!anyRunning) return;
    const timer = window.setInterval(() => void loadSnapshot(), 4000);
    return () => window.clearInterval(timer);
  }, [anyRunning, loadSnapshot]);

  async function save(patch: Partial<Pick<Board, "name" | "shared" | "widgets">>) {
    try {
      await api(`/api/boards/${boardId}`, { method: "PATCH", body: JSON.stringify(patch) });
      await Promise.all([loadBoards(), loadSnapshot()]);
    } catch (exc) {
      announceError(exc);
    }
  }

  function refreshWidget(widget: Widget) {
    return run(`refresh:${widget.agent_id}`, async () => {
      try {
        await api(`/api/agents/${widget.agent_id}/runs`, { method: "POST", body: "{}" });
        await loadSnapshot();
      } catch (exc) {
        announceError(exc);
      }
    });
  }

  function refreshAll() {
    if (!snap) return;
    void run("refresh:all", async () => {
      const targets = snap.widgets.filter((w) => w.state !== "running" && w.state !== "missing" && w.state !== "no_access" && w.can_run);
      const results = await Promise.allSettled(targets.map((w) => api(`/api/agents/${w.agent_id}/runs`, { method: "POST", body: "{}" })));
      const failed = results.filter((r) => r.status === "rejected").length;
      if (failed) notify({ tone: "error", title: `${failed} of ${targets.length} runs could not be started` });
      await loadSnapshot();
    });
  }

  async function createBoard() {
    const name = newName.trim();
    if (!name) return;
    try {
      const created = await api<Board>("/api/boards", { method: "POST", body: JSON.stringify({ name, widgets: [] }) });
      setCreating(false);
      setNewName("");
      await loadBoards();
      setParams({ b: created.id });
      setEditing(true);
    } catch (exc) {
      announceError(exc);
    }
  }

  async function deleteBoard() {
    try {
      await api(`/api/boards/${boardId}`, { method: "DELETE" });
      setConfirmDelete(false);
      setSnap(null);
      setParams({});
      await loadBoards();
    } catch (exc) {
      announceError(exc);
    }
  }

  function mutate(next: WidgetDef[]) {
    void save({ widgets: next });
  }
  function move(index: number, delta: number) {
    if (!snap) return;
    const list = [...snap.board.widgets];
    const target = index + delta;
    if (target < 0 || target >= list.length) return;
    [list[index], list[target]] = [list[target], list[index]];
    mutate(list);
  }

  const board = snap?.board;
  const used = new Set(board?.widgets.map((w) => w.agent_id));
  const addable = agents.filter((a) => a.status !== "deleted" && !used.has(a.id));

  if (error && !boards) return <div className="card"><p className="error">{presentText(error)}</p></div>;
  if (!boards) return <SkeletonRows />;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Boards</h1>
          <p className="muted">Pin the latest results of your agents on one screen.</p>
        </div>
        <div className="row">
          {board && <ActionButton className="btn-ghost" busy={pending("refresh:all")} busyLabel="Starting…" onClick={refreshAll} disabled={!board.widgets.length}><RefreshCw size={14} /> Refresh all</ActionButton>}
          {board?.owned && <button className="btn-ghost" type="button" onClick={() => setEditing((v) => !v)}>{editing ? <><Eye size={14} /> Done</> : <><Pencil size={14} /> Customize</>}</button>}
          {can("dashboard:read") && <button className="btn" type="button" onClick={() => setCreating(true)}><Plus size={14} /> New board</button>}
        </div>
      </div>

      {boards.length > 0 && (
        <div className="pills board-tabs" role="tablist">
          {boards.map((b) => (
            <button key={b.id} type="button" role="tab" aria-selected={b.id === boardId} className={b.id === boardId ? "on" : ""} onClick={() => setParams({ b: b.id })}>
              {b.name}{b.shared ? " · shared" : ""}
            </button>
          ))}
        </div>
      )}

      {boards.length === 0 && (
        <div className="card">
          <Empty title="No boards yet" body="Create a board and pin one or more agents to follow their results in one place." action={<button className="btn" type="button" onClick={() => setCreating(true)}><Plus size={14} /> New board</button>} />
        </div>
      )}

      {board && editing && (
        <div className="card board-edit">
          <div className="row">
            <input aria-label="Board name" defaultValue={board.name} key={board.id} onBlur={(e) => { const v = e.target.value.trim(); if (v && v !== board.name) void save({ name: v }); }} />
            <label className="row"><input type="checkbox" checked={board.shared} onChange={(e) => void save({ shared: e.target.checked })} /> Share with my group</label>
            <button className="btn-danger" type="button" onClick={() => setConfirmDelete(true)}><Trash2 size={14} /> Delete board</button>
          </div>
          <div className="row" style={{ marginTop: 12 }}>
            <div style={{ minWidth: 260, flex: 1 }}>
              <Select ariaLabel="Add agent" value={adding} onChange={setAdding} placeholder="Add an agent…" options={addable.map((a) => ({ value: a.id, label: a.name }))} />
            </div>
            <button className="btn" type="button" disabled={!adding} onClick={() => { mutate([...board.widgets, { id: "", agent_id: adding, size: "md" }]); setAdding(""); }}><Plus size={14} /> Add</button>
          </div>
        </div>
      )}

      {board && !snap && <SkeletonRows />}
      {snap && board && board.widgets.length === 0 && !editing && (
        <div className="card"><Empty title="This board is empty" body="Use Customize to pin agents." /></div>
      )}

      {snap && (
        <div className="board-grid">
          {snap.widgets.map((widget, index) => (
            <WidgetCard
              key={widget.id}
              widget={widget}
              editing={editing}
              refreshing={pending(`refresh:${widget.agent_id}`)}
              onRefresh={() => void refreshWidget(widget)}
              onRemove={() => mutate(snap.board.widgets.filter((w) => w.id !== widget.id))}
              onMove={(d) => move(index, d)}
              onSize={() => mutate(snap.board.widgets.map((w) => (w.id === widget.id ? { ...w, size: SIZES[(SIZES.indexOf(w.size) + 1) % SIZES.length] } : w)))}
              first={index === 0}
              last={index === snap.widgets.length - 1}
            />
          ))}
        </div>
      )}

      {creating && (
        <Modal title="New board" onClose={() => setCreating(false)}>
          <form onSubmit={(e) => { e.preventDefault(); void createBoard(); }}>
            <input autoFocus aria-label="Board name" placeholder="e.g. Daily sales" value={newName} onChange={(e) => setNewName(e.target.value)} style={{ width: "100%" }} />
            <div className="row" style={{ marginTop: 14, justifyContent: "flex-end" }}>
              <button className="btn-ghost" type="button" onClick={() => setCreating(false)}>Cancel</button>
              <button className="btn" type="submit" disabled={!newName.trim()}>Create</button>
            </div>
          </form>
        </Modal>
      )}
      {confirmDelete && board && (
        <ConfirmDialog title="Delete board?" body={`"${board.name}" will be removed. Agents and their runs are not affected.`} confirmLabel="Delete" onConfirm={() => void deleteBoard()} onClose={() => setConfirmDelete(false)} />
      )}
    </>
  );
}

function WidgetCard({ widget, editing, refreshing, onRefresh, onRemove, onMove, onSize, first, last }: {
  widget: Widget; editing: boolean; refreshing: boolean; onRefresh: () => void; onRemove: () => void; onMove: (delta: number) => void; onSize: () => void; first: boolean; last: boolean;
}) {
  const running = widget.state === "running";
  const result = widget.result;
  const shownAt = result?.finished_at || result?.created_at;
  return (
    <article className={`card board-widget size-${widget.size}${running ? " refreshing" : ""}${widget.state === "failed" ? " has-warning" : ""}`} aria-busy={running || undefined}>
      {running && <div className="refresh-bar" aria-hidden />}
      <header className="widget-head">
        <div className="widget-title">
          <h2>{widget.agent_name ?? "Unavailable agent"}</h2>
          {shownAt && <span className="muted">Result from {formatWhen(shownAt)}</span>}
        </div>
        <div className="row widget-actions">
          {running && widget.active_run && <Link className="btn-ghost follow" to={`/runs/${widget.active_run.id}`}><span className="live-dot" aria-hidden /> Follow</Link>}
          {widget.state !== "missing" && widget.state !== "no_access" && (
            <ActionButton className="btn-ghost icon-btn" busy={refreshing} busyLabel="" disabled={running || widget.can_run === false} title={running ? "A run is in progress" : "Run again and refresh"} onClick={onRefresh}>
              <RefreshCw size={15} aria-label="Refresh" />
            </ActionButton>
          )}
        </div>
      </header>

      {editing && (
        <div className="row widget-edit">
          <button className="btn-ghost" type="button" disabled={first} onClick={() => onMove(-1)} aria-label="Move earlier"><ArrowLeft size={14} /></button>
          <button className="btn-ghost" type="button" disabled={last} onClick={() => onMove(1)} aria-label="Move later"><ArrowRight size={14} /></button>
          <button className="btn-ghost" type="button" onClick={onSize}><LayoutGrid size={14} /> Size: {widget.size.toUpperCase()}</button>
          <button className="btn-danger" type="button" onClick={onRemove}><X size={14} /> Remove</button>
        </div>
      )}

      {running && (
        <div className="widget-note info" role="status">
          <span className="spinner" aria-hidden /> Refreshing… run started {formatWhen(widget.active_run?.started_at || widget.active_run?.created_at)}
          {result ? ". Showing the previous result meanwhile." : "."}
        </div>
      )}
      {widget.state === "failed" && widget.stale && (
        <div className="widget-note warn" role="alert">
          <AlertTriangle size={16} aria-hidden />
          <div>
            <strong>The latest run {widget.stale.status === "needs_review" ? "needs review" : "failed"} ({formatWhen(widget.stale.failed_at)}).</strong>{" "}
            {widget.stale.has_older_result ? "The data below is older and may be out of date." : "There is no earlier successful result to show."}
            {widget.stale.reason && <div className="widget-reason">{presentText(widget.stale.reason)}</div>}
            <Link to={`/runs/${widget.stale.run_id}`}>View failed run</Link>
          </div>
        </div>
      )}
      {widget.state === "missing" && <Empty title="Agent was deleted" body="Remove this widget from the board." />}
      {widget.state === "no_access" && <Empty title="No access" body="You do not have access to this agent." />}
      {widget.state === "empty" && <Empty title="No runs yet" body="Use refresh to run this agent." />}

      {result && (
        <div className={`widget-body${running || widget.state === "failed" ? " dimmed" : ""}`}>
          {result.report_markdown ? <ReportView text={result.report_markdown} /> : <p className="muted">This run produced no report.</p>}
          <footer className="widget-foot"><Badge status={result.status} /><Link to={`/runs/${result.id}`}>Open run</Link></footer>
        </div>
      )}
    </article>
  );
}
