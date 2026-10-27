import { api, ApiError } from "./api";
import { copy } from "./copy";
import { statusLabel } from "./format";

export type ToastTone = "success" | "info" | "warning" | "error";

export type ToastAction = {
  label: string;
  href?: string;
};

export type ToastInput = {
  tone?: ToastTone;
  title: string;
  body?: string;
  actions?: ToastAction[];
  duration?: number;
};

export type ToastItem = Required<Pick<ToastInput, "tone" | "title" | "duration">> & {
  id: string;
  body?: string;
  actions: ToastAction[];
};

type Listener = (items: ToastItem[]) => void;

let items: ToastItem[] = [];
const listeners = new Set<Listener>();
const watched = new Set<string>();

function emit() {
  for (const listener of listeners) listener(items);
}

export function getToasts(): ToastItem[] {
  return items;
}

export function subscribeToasts(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function notify(input: ToastInput): string {
  const id = crypto.randomUUID();
  const next: ToastItem = {
    id,
    tone: input.tone ?? "info",
    title: input.title,
    body: input.body,
    actions: input.actions ?? [],
    duration: input.duration ?? 6000,
  };
  items = [...items, next].slice(-5);
  emit();
  return id;
}

export function dismissToast(id: string) {
  items = items.filter((item) => item.id !== id);
  emit();
}

export function resetToasts() {
  items = [];
  watched.clear();
  emit();
}

export function announceRun(run: { id: string; agent_name?: string }, fallbackName: string) {
  const name = run.agent_name || fallbackName;
  notify({
    tone: "success",
    title: copy.runStarted(name),
    actions: [
      { label: copy.watchRun, href: `/runs/${run.id}` },
      { label: copy.viewAllRuns, href: "/runs" },
    ],
  });
  watchRun(run.id, name);
}

export function announceError(exc: unknown, fallback: string = copy.couldNotComplete) {
  notify({ tone: "error", title: exc instanceof ApiError ? exc.message : fallback });
}

const TERMINAL = new Set(["succeeded", "failed", "needs_review", "cancelled"]);

export function watchRun(id: string, name: string) {
  if (watched.has(id)) return;
  watched.add(id);
  const started = Date.now();
  const timer = window.setInterval(() => {
    if (Date.now() - started > 15 * 60 * 1000) {
      window.clearInterval(timer);
      watched.delete(id);
      return;
    }
    api<{ status: string }>(`/api/runs/${id}`).then((run) => {
      if (!TERMINAL.has(run.status)) return;
      window.clearInterval(timer);
      watched.delete(id);
      const label = statusLabel(run.status);
      notify({
        tone: run.status === "succeeded" ? "success" : run.status === "failed" ? "error" : "warning",
        title: copy.runFinished(label),
        body: name,
        actions: [{ label: copy.openReport, href: `/runs/${id}` }],
      });
    }).catch(() => {
      window.clearInterval(timer);
      watched.delete(id);
    });
  }, 3000);
}
