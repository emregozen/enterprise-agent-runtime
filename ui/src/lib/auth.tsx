import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { api, ApiError, setApiAuthContext } from "./api";

export type AuthGroup = {
  id: string;
  name: string;
  role: string;
};

export type AuthUser = {
  id: string | null;
  email: string;
  display_name: string;
  status: string;
  is_admin: boolean;
};

export type AuthMe = {
  auth_mode: string;
  authenticated: boolean;
  user: AuthUser | null;
  groups: AuthGroup[];
  active_group_id: string | null;
  permissions: string[];
  csrf_token: string | null;
};

type AuthContextValue = {
  me: AuthMe;
  loading: boolean;
  can: (permission: string) => boolean;
  switchGroup: (groupId: string) => Promise<void>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
};

const DEFAULT_ME: AuthMe = {
  auth_mode: "disabled",
  authenticated: true,
  user: {
    id: null,
    email: "local-dev@agent-runtime.local",
    display_name: "Local Operator",
    status: "active",
    is_admin: true,
  },
  groups: [{ id: "00000000-0000-4000-8000-000000000001", name: "default", role: "editor" }],
  active_group_id: "00000000-0000-4000-8000-000000000001",
  permissions: ["*"],
  csrf_token: null,
};

const AuthContext = createContext<AuthContextValue>({
  me: DEFAULT_ME,
  loading: false,
  can: () => true,
  switchGroup: async () => undefined,
  logout: async () => undefined,
  refresh: async () => undefined,
});

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<AuthMe>(DEFAULT_ME);
  const [loading, setLoading] = useState(true);

  async function refresh() {
    try {
      const body = await api<AuthMe>("/api/auth/me");
      setApiAuthContext({
        csrfToken: body.csrf_token,
        activeGroupId: body.active_group_id,
      });
      setMe(body);
    } catch (exc) {
      if (exc instanceof ApiError && exc.status === 401) {
        setApiAuthContext({ csrfToken: null, activeGroupId: null });
        setMe({
          auth_mode: "oidc",
          authenticated: false,
          user: null,
          groups: [],
          active_group_id: null,
          permissions: [],
          csrf_token: null,
        });
      } else {
        setMe(DEFAULT_ME);
      }
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void refresh();
  }, []);

  function can(permission: string): boolean {
    if (me.auth_mode === "disabled") return true;
    if (!me.authenticated || !me.user || me.user.status !== "active") return false;
    if (me.user.is_admin) return true;
    if (me.permissions.includes("*")) return true;
    return me.permissions.includes(permission);
  }

  async function switchGroup(groupId: string) {
    setApiAuthContext({ activeGroupId: groupId });
    try {
      const body = await api<AuthMe>("/api/auth/active-group", {
        method: "POST",
        body: JSON.stringify({ group_id: groupId }),
      });
      setApiAuthContext({
        csrfToken: body.csrf_token,
        activeGroupId: body.active_group_id,
      });
      setMe(body);
    } catch {
      await refresh();
    }
  }

  async function logout() {
    try {
      const res = await api<{ ok: boolean; logout_url?: string | null }>("/api/auth/logout", {
        method: "POST",
      });
      setApiAuthContext({ csrfToken: null, activeGroupId: null });
      if (res.logout_url) {
        window.location.assign(res.logout_url);
        return;
      }
    } catch {
      /* ignore */
    }
    await refresh();
  }

  return (
    <AuthContext.Provider value={{ me, loading, can, switchGroup, logout, refresh }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
