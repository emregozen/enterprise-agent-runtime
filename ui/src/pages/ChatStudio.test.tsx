import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ChatStudio } from "../components/ChatStudio";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("ChatStudio", () => {
  it("loads datasources, sends a question, and renders guarded SQL and rows", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo, init?: RequestInit): Promise<{ ok: boolean; status: number; json: () => Promise<unknown>; text: () => Promise<string> }> => {
        const url = String(input);
        if (url.endsWith("/api/datasources")) {
          return {
            ok: true,
            status: 200,
            json: async () => [
              {
                id: "ds-1",
                name: "postgres-sales",
                dialect: "postgres",
                allow_tables: ["sales"],
                sensitivity: "internal",
                enabled: true,
              },
            ],
            text: async () => "",
          };
        }
        if (url.endsWith("/api/chat/ask") && init?.method === "POST") {
          return {
            ok: true,
            status: 200,
            json: async () => ({
              session: {
                id: "sess-1",
                title: "Regional sales breakdown",
                datasource_name: "postgres-sales",
                model_ref: null,
                created_at: "2026-10-28T12:00:00Z",
                updated_at: "2026-10-28T12:00:01Z",
              },
              user_message: {
                id: "msg-1",
                session_id: "sess-1",
                ordinal: 1,
                role: "user",
                content: "Compare sales by region",
                sql: null,
                columns: [],
                rows: [],
                row_count: 0,
                latency_ms: null,
                status: "succeeded",
                error: null,
                guard_info: {},
                follow_ups: [],
                created_at: "2026-10-28T12:00:00Z",
              },
              assistant_message: {
                id: "msg-2",
                session_id: "sess-1",
                ordinal: 2,
                role: "assistant",
                content: "Marmara leads total sales.",
                sql: "SELECT region, SUM(amount) AS total FROM sales GROUP BY region",
                columns: ["region", "total"],
                rows: [{ region: "Marmara", total: 125000 }],
                row_count: 1,
                latency_ms: 84,
                status: "succeeded",
                error: null,
                guard_info: { dialect: "postgres", tables: ["sales"], aggregate: true, read_only: true },
                follow_ups: ["Show daily trend"],
                created_at: "2026-10-28T12:00:01Z",
              },
            }),
            text: async () => "",
          };
        }
        return { ok: true, status: 200, json: async () => [], text: async () => "" };
      }),
    );

    const { container } = render(
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route path="/" element={<ChatStudio mode="hero" />} />
        </Routes>
      </MemoryRouter>,
    );

    expect((await screen.findAllByText("postgres-sales")).length).toBeGreaterThanOrEqual(1);
    const input = screen.getByPlaceholderText(/Ask a question about this data source/i);
    await userEvent.type(input, "Compare sales by region{Enter}");

    expect(await screen.findByText("Marmara leads total sales.")).toBeInTheDocument();
    expect(screen.getByText("Marmara")).toBeInTheDocument();
    expect(screen.getByText("125,000")).toBeInTheDocument();

    const sqlBtn = screen.getByRole("button", { name: /Verified SQL/i });
    await userEvent.click(sqlBtn);
    expect(container.querySelector(".code")?.textContent).toContain("SELECT region, SUM(amount)");
  });
});
