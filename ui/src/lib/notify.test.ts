import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./api", () => ({
  api: vi.fn(),
  ApiError: class ApiError extends Error {
    status: number;
    constructor(message: string, status: number) {
      super(message);
      this.status = status;
    }
  },
}));

import { ApiError, api } from "./api";
import { announceError, getToasts, resetToasts, watchRun } from "./notify";

describe("notify", () => {
  beforeEach(() => {
    resetToasts();
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
    resetToasts();
  });

  it("shows the presented error message", () => {
    announceError(new ApiError("This agent already has a running run", 409));
    expect(getToasts()[0]).toMatchObject({ tone: "error", title: "This agent already has a running run" });
  });

  it("follows a run started in the console until it finishes", async () => {
    vi.mocked(api).mockResolvedValue({ status: "failed" });
    watchRun("run-9", "stok-esigi");
    await vi.advanceTimersByTimeAsync(3000);
    expect(getToasts().some((item) => item.title === "Run failed" && item.body === "stok-esigi" && item.actions[0]?.href === "/runs/run-9")).toBe(true);
  });
});
