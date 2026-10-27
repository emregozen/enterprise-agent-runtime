import { AlertTriangle, CheckCircle2, Info, X, XCircle } from "lucide-react";
import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { Link } from "react-router-dom";
import { copy } from "../lib/copy";
import { dismissToast, getToasts, subscribeToasts, type ToastItem, type ToastTone } from "../lib/notify";

const ICONS: Record<ToastTone, typeof Info> = {
  success: CheckCircle2,
  info: Info,
  warning: AlertTriangle,
  error: XCircle,
};

function prefersReducedMotion() {
  return typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

export function Toaster() {
  const items = useSyncExternalStore(subscribeToasts, getToasts, getToasts);
  return (
    <div className="toasts" aria-live="polite" aria-relevant="additions">
      {items.map((item) => <ToastCard key={item.id} item={item} />)}
    </div>
  );
}

function ToastCard({ item }: { item: ToastItem }) {
  const Icon = ICONS[item.tone];
  const reduced = prefersReducedMotion();
  const [hovered, setHovered] = useState(false);
  const remaining = useRef(item.duration);

  useEffect(() => {
    if (!reduced || item.duration <= 0 || hovered) return;
    const startedAt = Date.now();
    const timer = window.setTimeout(() => dismissToast(item.id), remaining.current);
    return () => {
      remaining.current = Math.max(0, remaining.current - (Date.now() - startedAt));
      window.clearTimeout(timer);
    };
  }, [hovered, reduced, item.id, item.duration]);

  return (
    <article
      className={`toast ${item.tone}`}
      role="status"
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      <Icon size={18} aria-hidden />
      <div className="toast-copy">
        <strong>{item.title}</strong>
        {item.body && <p>{item.body}</p>}
        {item.actions.length > 0 && (
          <div className="toast-actions">
            {item.actions.map((action, index) => (
              action.href
                ? <Link key={action.href + action.label} className={index === 0 ? "btn" : "toast-link"} to={action.href}>{action.label}</Link>
                : <span key={action.label}>{action.label}</span>
            ))}
          </div>
        )}
      </div>
      <button type="button" className="toast-close" aria-label={copy.close} onClick={() => dismissToast(item.id)}><X size={14} /></button>
      {item.duration > 0 && !reduced && (
        <span
          className="toast-progress"
          style={{ animationDuration: `${item.duration}ms`, animationPlayState: hovered ? "paused" : "running" }}
          onAnimationEnd={() => { if (!hovered) dismissToast(item.id); }}
        />
      )}
    </article>
  );
}
