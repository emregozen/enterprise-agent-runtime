import { useEffect, useState } from "react";
import { ActionButton, Badge, Empty, Modal, SkeletonRows } from "../components/ui";
import { api, ApiError } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useBusy } from "../lib/busy";
import { copy } from "../lib/copy";
import { formatWhen } from "../lib/format";
import { announceError, notify } from "../lib/notify";

type UserMembership = {
  group_id: string;
  group_name: string;
  role: string;
};

type AdminUser = {
  id: string;
  email: string;
  display_name: string;
  status: string;
  is_admin: boolean;
  idp_groups?: string[];
  memberships?: UserMembership[];
  groups?: UserMembership[];
  created_at: string | null;
  last_login_at: string | null;
};

type AdminGroup = {
  id: string;
  name: string;
  description: string;
  member_count: number;
  created_at: string | null;
};

type AuditItem = {
  id: string;
  ts: string | null;
  actor: string;
  action: string;
  entity_type: string;
  entity_id: string;
  detail: Record<string, unknown>;
};

const ROLES = [
  { value: "viewer", label: copy.roleViewer },
  { value: "operator", label: copy.roleOperator },
  { value: "editor", label: copy.roleEditor },
];

export function AdminPage() {
  const { me } = useAuth();
  const [tab, setTab] = useState<"pending" | "users" | "groups" | "audit">("pending");
  const [users, setUsers] = useState<AdminUser[] | null>(null);
  const [groups, setGroups] = useState<AdminGroup[] | null>(null);
  const [audits, setAudits] = useState<AuditItem[] | null>(null);
  const [error, setError] = useState("");
  const [approvalSelections, setApprovalSelections] = useState<Record<string, { groupId: string; role: string }>>({});
  const [memberDrafts, setMemberDrafts] = useState<Record<string, { groupId: string; role: string }>>({});
  const [newGroupModal, setNewGroupModal] = useState<{ name: string; description: string } | null>(null);
  const [auditActor, setAuditActor] = useState("");
  const [auditAction, setAuditAction] = useState("");
  const { run, pending } = useBusy();

  function loadAll() {
    Promise.all([
      api<AdminUser[]>("/api/admin/users"),
      api<AdminGroup[]>("/api/admin/groups"),
      api<AuditItem[]>("/api/admin/audit?limit=100"),
    ])
      .then(([u, g, a]) => {
        setUsers(u);
        setGroups(g);
        setAudits(a);
        const defaultGroup = g.find((item) => item.name === "default")?.id || g[0]?.id || "";
        setApprovalSelections((prev) => {
          const next = { ...prev };
          for (const usr of u) {
            if (!next[usr.id]) {
              next[usr.id] = { groupId: defaultGroup, role: "viewer" };
            }
          }
          return next;
        });
      })
      .catch((exc: ApiError) => setError(exc.message));
  }

  useEffect(loadAll, []);

  function loadAudit() {
    const params = new URLSearchParams({ limit: "100" });
    if (auditActor.trim()) params.set("actor", auditActor.trim());
    if (auditAction.trim()) params.set("action", auditAction.trim());
    api<AuditItem[]>(`/api/admin/audit?${params}`)
      .then(setAudits)
      .catch((exc: ApiError) => announceError(exc));
  }

  function approveUser(user: AdminUser) {
    const choice = approvalSelections[user.id] || {
      groupId: groups?.[0]?.id || "",
      role: "viewer",
    };
    void run(`approve:${user.id}`, async () => {
      try {
        await api(`/api/admin/users/${user.id}/approve`, {
          method: "POST",
          body: JSON.stringify({ group_id: choice.groupId, role: choice.role }),
        });
        notify({ tone: "success", title: copy.userApproved(user.email) });
        loadAll();
      } catch (exc) {
        announceError(exc);
      }
    });
  }

  function rejectUser(user: AdminUser) {
    void run(`reject:${user.id}`, async () => {
      try {
        await api(`/api/admin/users/${user.id}/reject`, { method: "POST" });
        notify({ tone: "info", title: copy.userRejected(user.email) });
        loadAll();
      } catch (exc) {
        announceError(exc);
      }
    });
  }

  function patchUser(user: AdminUser, payload: { status?: string; is_admin?: boolean }) {
    void run(`patch:${user.id}`, async () => {
      try {
        await api(`/api/admin/users/${user.id}`, {
          method: "PATCH",
          body: JSON.stringify(payload),
        });
        notify({ tone: "success", title: copy.saved });
        loadAll();
      } catch (exc) {
        announceError(exc);
      }
    });
  }

  function addMembership(user: AdminUser) {
    const defaultGroup = groups?.[0]?.id || "";
    const draft = memberDrafts[user.id] || { groupId: defaultGroup, role: "viewer" };
    if (!draft.groupId) return;
    void run(`member:${user.id}`, async () => {
      try {
        await api(`/api/admin/groups/${draft.groupId}/members`, {
          method: "POST",
          body: JSON.stringify({ user_id: user.id, role: draft.role }),
        });
        notify({ tone: "success", title: copy.saved });
        loadAll();
      } catch (exc) {
        announceError(exc);
      }
    });
  }

  function removeMembership(userId: string, groupId: string) {
    void run(`rm:${userId}:${groupId}`, async () => {
      try {
        await api(`/api/admin/groups/${groupId}/members/${userId}`, {
          method: "DELETE",
        });
        notify({ tone: "success", title: copy.deleted });
        loadAll();
      } catch (exc) {
        announceError(exc);
      }
    });
  }

  function createGroup() {
    if (!newGroupModal) return;
    void run("create-group", async () => {
      try {
        const created = await api<AdminGroup>("/api/admin/groups", {
          method: "POST",
          body: JSON.stringify(newGroupModal),
        });
        notify({ tone: "success", title: copy.groupCreated(created.name) });
        setNewGroupModal(null);
        loadAll();
      } catch (exc) {
        announceError(exc, copy.couldNotSave);
      }
    });
  }

  function deleteGroup(group: AdminGroup) {
    void run(`del-group:${group.id}`, async () => {
      try {
        await api(`/api/admin/groups/${group.id}`, { method: "DELETE" });
        notify({ tone: "success", title: copy.groupDeleted(group.name) });
        loadAll();
      } catch (exc) {
        announceError(exc);
      }
    });
  }

  if (me.auth_mode === "oidc" && !me.user?.is_admin) {
    return <div className="card">{copy.permissionDeniedHint}</div>;
  }
  if (error) return <div className="card">{error}</div>;
  if (!users || !groups || !audits) return <SkeletonRows />;

  const userMemberships = (u: AdminUser): UserMembership[] => u.memberships || u.groups || [];
  const pendingUsers = users.filter((u) => u.status === "pending" || (u.status === "active" && !u.is_admin && userMemberships(u).length === 0));

  return (
    <>
      <div className="page-head">
        <div>
          <p className="eyebrow">{copy.navAdmin}</p>
          <h1>{copy.adminTitle}</h1>
          <p>{copy.adminLead}</p>
        </div>
        {tab === "groups" && (
          <button className="btn" type="button" onClick={() => setNewGroupModal({ name: "", description: "" })}>
            {copy.newGroup}
          </button>
        )}
      </div>

      <div className="tabs">
        <button className={tab === "pending" ? "on" : ""} type="button" onClick={() => setTab("pending")}>
          {copy.tabPending} ({pendingUsers.length})
        </button>
        <button className={tab === "users" ? "on" : ""} type="button" onClick={() => setTab("users")}>
          {copy.tabUsers} ({users.length})
        </button>
        <button className={tab === "groups" ? "on" : ""} type="button" onClick={() => setTab("groups")}>
          {copy.tabGroups} ({groups.length})
        </button>
        <button className={tab === "audit" ? "on" : ""} type="button" onClick={() => setTab("audit")}>
          {copy.tabAudit}
        </button>
      </div>

      {tab === "pending" && (
        <section className="card">
          {pendingUsers.length === 0 ? (
            <Empty title={copy.noPendingUsers} body={copy.noPendingUsersBody} />
          ) : (
            <div className="list">
              {pendingUsers.map((user) => {
                const choice = approvalSelections[user.id] || {
                  groupId: groups[0]?.id || "",
                  role: "viewer",
                };
                return (
                  <article className="card list-row" key={user.id}>
                    <div>
                      <h2>{user.display_name || user.email}</h2>
                      <p className="lede" style={{ margin: 0 }}>
                        {user.email} · requested {formatWhen(user.created_at)}
                      </p>
                    </div>
                    <label className="field" style={{ margin: 0 }}>
                      <span>Group</span>
                      <select
                        aria-label={`Group for ${user.email}`}
                        value={choice.groupId}
                        onChange={(e) =>
                          setApprovalSelections({
                            ...approvalSelections,
                            [user.id]: { ...choice, groupId: e.target.value },
                          })
                        }
                      >
                        {groups.map((g) => (
                          <option key={g.id} value={g.id}>
                            {g.name}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className="field" style={{ margin: 0 }}>
                      <span>Role</span>
                      <select
                        aria-label={`Role for ${user.email}`}
                        value={choice.role}
                        onChange={(e) =>
                          setApprovalSelections({
                            ...approvalSelections,
                            [user.id]: { ...choice, role: e.target.value },
                          })
                        }
                      >
                        {ROLES.map((r) => (
                          <option key={r.value} value={r.value}>
                            {r.label}
                          </option>
                        ))}
                      </select>
                    </label>
                    <div className="row">
                      <ActionButton busy={pending(`approve:${user.id}`)} onClick={() => approveUser(user)}>
                        {copy.approve}
                      </ActionButton>
                      <ActionButton
                        className="btn-danger"
                        busy={pending(`reject:${user.id}`)}
                        onClick={() => rejectUser(user)}
                      >
                        {copy.reject}
                      </ActionButton>
                    </div>
                  </article>
                );
              })}
            </div>
          )}
        </section>
      )}

      {tab === "users" && (
        <section className="card">
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>User</th>
                  <th>Status</th>
                  <th>Groups & roles</th>
                  <th>Assign group</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {users.map((user) => {
                  const draft = memberDrafts[user.id] || {
                    groupId: groups[0]?.id || "",
                    role: "viewer",
                  };
                  return (
                    <tr key={user.id}>
                      <td>
                        <strong>{user.display_name || user.email}</strong>
                        <div className="lede">{user.email}</div>
                      </td>
                      <td>
                        <div className="row">
                          <Badge
                            status={
                              user.status === "active"
                                ? "published"
                                : user.status === "pending"
                                  ? "pending"
                                  : "failed"
                            }
                          />
                          {user.is_admin && <span className="badge info">{copy.roleAdmin}</span>}
                        </div>
                      </td>
                      <td>
                        <div className="row" style={{ flexWrap: "wrap", gap: 6 }}>
                          {userMemberships(user).length === 0 && <span className="lede">—</span>}
                          {userMemberships(user).map((m) => (
                            <span key={m.group_id} className="badge">
                              {m.group_name} ({m.role}){" "}
                              <button
                                type="button"
                                className="btn-ghost"
                                aria-label={`Remove ${user.email} from ${m.group_name}`}
                                style={{ padding: "0 4px", marginLeft: 4 }}
                                onClick={() => removeMembership(user.id, m.group_id)}
                              >
                                ×
                              </button>
                            </span>
                          ))}
                        </div>
                      </td>
                      <td>
                        <div className="row">
                          <select
                            aria-label={`Assign group for ${user.email}`}
                            value={draft.groupId}
                            onChange={(e) =>
                              setMemberDrafts({
                                ...memberDrafts,
                                [user.id]: { ...draft, groupId: e.target.value },
                              })
                            }
                          >
                            {groups.map((g) => (
                              <option key={g.id} value={g.id}>
                                {g.name}
                              </option>
                            ))}
                          </select>
                          <select
                            aria-label={`Assign role for ${user.email}`}
                            value={draft.role}
                            onChange={(e) =>
                              setMemberDrafts({
                                ...memberDrafts,
                                [user.id]: { ...draft, role: e.target.value },
                              })
                            }
                          >
                            {ROLES.map((r) => (
                              <option key={r.value} value={r.value}>
                                {r.label}
                              </option>
                            ))}
                          </select>
                          <ActionButton
                            className="btn-ghost"
                            busy={pending(`member:${user.id}`)}
                            onClick={() => addMembership(user)}
                          >
                            {copy.addMember}
                          </ActionButton>
                        </div>
                      </td>
                      <td>
                        <div className="row">
                          <button
                            className="btn-ghost"
                            type="button"
                            onClick={() => patchUser(user, { is_admin: !user.is_admin })}
                          >
                            {user.is_admin ? copy.revokeAdmin : copy.grantAdmin}
                          </button>
                          <button
                            className="btn-ghost"
                            type="button"
                            onClick={() =>
                              patchUser(user, { status: user.status === "active" ? "disabled" : "active" })
                            }
                          >
                            {user.status === "active" ? copy.disableUser : copy.enableUser}
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {tab === "groups" && (
        <section className="card">
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>{copy.groupName}</th>
                  <th>{copy.groupDescription}</th>
                  <th>{copy.members}</th>
                  <th>Created</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {groups.map((group) => (
                  <tr key={group.id}>
                    <td>
                      <strong>{group.name}</strong>
                    </td>
                    <td>{group.description || "—"}</td>
                    <td>{group.member_count}</td>
                    <td>{formatWhen(group.created_at)}</td>
                    <td>
                      {group.name !== "default" && (
                        <ActionButton
                          className="btn-danger"
                          busy={pending(`del-group:${group.id}`)}
                          onClick={() => deleteGroup(group)}
                        >
                          {copy.delete}
                        </ActionButton>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {tab === "audit" && (
        <section className="card">
          <div className="row" style={{ marginBottom: 12 }}>
            <input
              className="search"
              placeholder="Filter by actor"
              aria-label="Filter by actor"
              value={auditActor}
              onChange={(e) => setAuditActor(e.target.value)}
            />
            <input
              className="search"
              placeholder="Filter by action"
              aria-label="Filter by action"
              value={auditAction}
              onChange={(e) => setAuditAction(e.target.value)}
            />
            <button className="btn-ghost" type="button" onClick={loadAudit}>
              {copy.filter}
            </button>
          </div>
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>When</th>
                  <th>Actor</th>
                  <th>Action</th>
                  <th>Entity</th>
                  <th>Detail</th>
                </tr>
              </thead>
              <tbody>
                {audits.map((item) => (
                  <tr key={item.id}>
                    <td>{formatWhen(item.ts)}</td>
                    <td>{item.actor}</td>
                    <td>
                      <code>{item.action}</code>
                    </td>
                    <td>
                      {item.entity_type}:{item.entity_id}
                    </td>
                    <td>
                      <code>{JSON.stringify(item.detail)}</code>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {newGroupModal && (
        <Modal title={copy.newGroup} onClose={() => setNewGroupModal(null)}>
          <div className="grid-2">
            <label className="field">
              {copy.groupName}
              <input
                value={newGroupModal.name}
                placeholder="analytics-team"
                onChange={(e) => setNewGroupModal({ ...newGroupModal, name: e.target.value })}
              />
            </label>
            <label className="field">
              {copy.groupDescription}
              <input
                value={newGroupModal.description}
                placeholder="Analytics & BI operators"
                onChange={(e) => setNewGroupModal({ ...newGroupModal, description: e.target.value })}
              />
            </label>
          </div>
          <div className="row" style={{ marginTop: 12 }}>
            <ActionButton busy={pending("create-group")} onClick={createGroup}>
              {copy.save}
            </ActionButton>
            <button className="btn-ghost" type="button" onClick={() => setNewGroupModal(null)}>
              {copy.cancel}
            </button>
          </div>
        </Modal>
      )}
    </>
  );
}
