import { useLocation } from "react-router-dom";
import { Badge } from "../components/ui";
import { useAuth } from "../lib/auth";
import { copy } from "../lib/copy";

export function LoginPage() {
  const { me, refresh, logout } = useAuth();
  const location = useLocation();
  const nextPath = `${location.pathname}${location.search}` || "/";
  const loginHref = `/backend/api/auth/login?next=${encodeURIComponent(nextPath)}`;

  if (!me.authenticated || !me.user) {
    return (
      <div className="auth-gate" style={{ minHeight: "100vh", display: "grid", placeItems: "center", padding: 24 }}>
        <section className="card" style={{ maxWidth: 460, width: "100%" }}>
          <div className="brand" style={{ marginBottom: 16 }}>
            <span className="mark" aria-hidden />
            <span>
              <span>Control plane</span>
              <strong>{copy.product}</strong>
            </span>
          </div>
          <h1>{copy.signInTitle}</h1>
          <p className="lede">{copy.signInLead}</p>
          <div className="row" style={{ marginTop: 20 }}>
            <a className="btn" href={loginHref}>
              {copy.signInButton}
            </a>
          </div>
        </section>
      </div>
    );
  }

  const status = me.user.status;
  const title =
    status === "rejected"
      ? copy.rejectedTitle
      : status === "disabled"
        ? copy.disabledTitle
        : copy.awaitingApprovalTitle;
  const body =
    status === "rejected"
      ? copy.rejectedBody
      : status === "disabled"
        ? copy.disabledBody
        : copy.awaitingApprovalBody;

  return (
    <div className="auth-gate" style={{ minHeight: "100vh", display: "grid", placeItems: "center", padding: 24 }}>
      <section className="card" style={{ maxWidth: 520, width: "100%" }}>
        <div className="row" style={{ justifyContent: "space-between", marginBottom: 12 }}>
          <div className="brand">
            <span className="mark" aria-hidden />
            <span>
              <span>Control plane</span>
              <strong>{copy.product}</strong>
            </span>
          </div>
          <Badge status={status === "rejected" || status === "disabled" ? "failed" : "pending"} />
        </div>
        <h1>{title}</h1>
        <p className="lede">{body}</p>
        <dl className="agent-meta" style={{ marginTop: 16 }}>
          <div>
            <dt>Name</dt>
            <dd>{me.user.display_name || "—"}</dd>
          </div>
          <div>
            <dt>Email</dt>
            <dd>{me.user.email}</dd>
          </div>
        </dl>
        <div className="row" style={{ marginTop: 20 }}>
          {status === "pending" && (
            <button className="btn" type="button" onClick={() => void refresh()}>
              {copy.checkStatus}
            </button>
          )}
          <button className="btn-ghost" type="button" onClick={() => void logout()}>
            {copy.signOut}
          </button>
        </div>
      </section>
    </div>
  );
}
