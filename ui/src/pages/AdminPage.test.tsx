import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AuthProvider } from "../lib/auth";
import { AdminPage } from "./AdminPage";
import { LoginPage } from "./LoginPage";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("LoginPage & AdminPage", () => {
  it("renders the awaiting approval screen when user status is pending", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: true,
        status: 200,
        json: async () => ({
          auth_mode: "oidc",
          authenticated: true,
          user: {
            id: "u-pending",
            email: "newuser@company.example",
            display_name: "New User",
            status: "pending",
            is_admin: false,
          },
          groups: [],
          active_group_id: null,
          permissions: [],
          csrf_token: "csrf-1",
        }),
      })),
    );
    render(
      <MemoryRouter>
        <AuthProvider>
          <LoginPage />
        </AuthProvider>
      </MemoryRouter>,
    );
    expect(await screen.findByRole("heading", { name: "Awaiting administrator approval" })).toBeInTheDocument();
    expect(screen.getByText("newuser@company.example")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Check status" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign out" })).toBeInTheDocument();
  });

  it("lets an admin approve a pending user and assign a group and role", async () => {
    const user = userEvent.setup();
    const calls: { url: string; method?: string; body?: string }[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo, init?: RequestInit) => {
        const url = String(input);
        calls.push({ url, method: init?.method, body: init?.body ? String(init.body) : undefined });
        if (url.endsWith("/api/admin/users")) {
          return {
            ok: true,
            status: 200,
            json: async () => [
              {
                id: "u-1",
                email: "alice@company.example",
                display_name: "Alice",
                status: "pending",
                is_admin: false,
                idp_groups: [],
                memberships: [],
                created_at: "2026-10-28T08:00:00Z",
                last_login_at: "2026-10-28T08:00:00Z",
              },
            ],
          };
        }
        if (url.endsWith("/api/admin/groups")) {
          return {
            ok: true,
            status: 200,
            json: async () => [
              {
                id: "00000000-0000-4000-8000-000000000001",
                name: "default",
                description: "Default group",
                member_count: 1,
                created_at: "2026-10-28T08:00:00Z",
              },
              {
                id: "00000000-0000-4000-8000-000000000002",
                name: "finance",
                description: "Finance team",
                member_count: 2,
                created_at: "2026-10-28T08:00:00Z",
              },
            ],
          };
        }
        if (url.includes("/api/admin/audit")) {
          return {
            ok: true,
            status: 200,
            json: async () => [
              {
                id: "a-1",
                ts: "2026-10-28T08:01:00Z",
                actor: "admin@company.example",
                action: "user.approved",
                entity_type: "user",
                entity_id: "u-1",
                detail: { role: "operator" },
              },
            ],
          };
        }
        return { ok: true, status: 200, json: async () => ({}) };
      }),
    );

    render(<AdminPage />);
    expect(await screen.findByRole("heading", { name: "Access & governance" })).toBeInTheDocument();
    expect(screen.getByText("Alice")).toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText("Group for alice@company.example"), "00000000-0000-4000-8000-000000000002");
    await user.selectOptions(screen.getByLabelText("Role for alice@company.example"), "operator");
    await user.click(screen.getByRole("button", { name: "Approve" }));

    const approveCall = calls.find((c) => c.url.endsWith("/api/admin/users/u-1/approve"));
    expect(approveCall).toBeDefined();
    expect(JSON.parse(approveCall!.body!)).toEqual({
      group_id: "00000000-0000-4000-8000-000000000002",
      role: "operator",
    });
  });
});
