import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, vi } from "vitest";
import { RunDetail } from "./RunDetail";

const recorded = [
  { ordinal: 1, name: "plan", status: "succeeded", detail: {}, created_at: "2026-10-27T12:00:00Z" },
  { ordinal: 2, name: "report", status: "succeeded", detail: {}, created_at: "2026-10-27T12:01:00Z" },
];

function run(status: string) {
  return {
    id: "run-1",
    agent_id: "agent-1",
    agent_name: "bolgesel-satis-karsilastirma-ozeti",
    status,
    error: null,
    needs_review_reason: null,
    report_markdown: "Report",
    created_at: "2026-10-27T12:00:00Z",
    started_at: "2026-10-27T12:00:00Z",
    finished_at: status === "pending" || status === "running" ? null : "2026-10-27T12:02:00Z",
    spec: { spec: { goal: "Compare regions" } },
    summary: {},
    steps: recorded,
    artifacts: [],
    deliveries: [],
  };
}

function renderRun(status: string) {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo) => {
    const url = String(input);
    const body = url.endsWith("/logs") ? { text: "" } : run(status);
    return { ok: true, status: 200, json: async () => body, text: async () => "" };
  }));
  render(
    <MemoryRouter initialEntries={["/runs/run-1"]}>
      <Routes>
        <Route path="/runs/:id" element={<RunDetail />} />
      </Routes>
    </MemoryRouter>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Run pipeline", () => {
  it("marks unused steps as skipped once the run has finished", async () => {
    renderRun("succeeded");
    const skipped = await screen.findAllByTitle("Did not run");
    expect(skipped.map((node) => node.textContent)).toEqual([
      "Skipped", "Skipped", "Skipped", "Skipped", "Skipped", "Skipped", "Skipped",
    ]);
    expect(skipped.every((node) => node.classList.contains("muted"))).toBe(true);
    expect(screen.getAllByText("Succeeded")).toHaveLength(3);
    expect(screen.queryByText("Waiting")).not.toBeInTheDocument();
  });

  it("keeps waiting only while the run is still open", async () => {
    renderRun("running");
    expect(await screen.findAllByText("Waiting")).toHaveLength(7);
    expect(screen.queryByTitle("Did not run")).not.toBeInTheDocument();
    expect(screen.queryByText("Skipped")).not.toBeInTheDocument();
  });
});
