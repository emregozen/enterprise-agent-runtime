import "@testing-library/jest-dom/vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { notify, resetToasts } from "../lib/notify";
import { Toaster } from "./Toaster";

function mockMotion(matches: boolean) {
  window.matchMedia = ((query: string) => ({
    matches: query.includes("reduce") ? matches : false,
    media: query,
    addEventListener() {},
    removeEventListener() {},
    addListener() {},
    removeListener() {},
    dispatchEvent() { return false; },
    onchange: null,
  })) as typeof window.matchMedia;
}

describe("Toaster", () => {
  beforeEach(() => {
    resetToasts();
    mockMotion(false);
  });
  afterEach(() => {
    cleanup();
    resetToasts();
    vi.useRealTimers();
  });

  it("shows a success toast with an action and dismisses it from the close button", async () => {
    render(<MemoryRouter><Toaster /></MemoryRouter>);
    act(() => {
      notify({
        tone: "success",
        title: "Run started for gunluk-satis-ozeti",
        actions: [
          { label: "Watch run", href: "/runs/abc" },
          { label: "View all runs", href: "/runs" },
        ],
      });
    });
    expect(screen.getByText("Run started for gunluk-satis-ozeti")).toBeInTheDocument();
    const watch = screen.getByRole("link", { name: "Watch run" });
    expect(watch).toHaveClass("btn");
    expect(watch).toHaveAttribute("href", "/runs/abc");
    expect(screen.getByRole("link", { name: "View all runs" })).toHaveClass("toast-link");
    expect(document.querySelector(".toast.success .toast-progress")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.queryByText("Run started for gunluk-satis-ozeti")).not.toBeInTheDocument();
  });

  it("uses the error tone for a presented error", () => {
    render(<MemoryRouter><Toaster /></MemoryRouter>);
    act(() => {
      notify({ tone: "error", title: "This agent already has a running run" });
    });
    expect(document.querySelector(".toast.error")).toBeTruthy();
    expect(screen.getByText("This agent already has a running run")).toBeInTheDocument();
  });

  it("pauses auto-dismiss while the pointer is over the toast", async () => {
    mockMotion(true);
    vi.useFakeTimers();
    render(<MemoryRouter><Toaster /></MemoryRouter>);
    act(() => {
      notify({ title: "Saved", duration: 6000 });
    });
    expect(screen.getByText("Saved")).toBeInTheDocument();
    await act(async () => { await vi.advanceTimersByTimeAsync(4000); });
    fireEvent.mouseEnter(screen.getByRole("status"));
    await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
    expect(screen.getByText("Saved")).toBeInTheDocument();
    fireEvent.mouseLeave(screen.getByRole("status"));
    await act(async () => { await vi.advanceTimersByTimeAsync(2500); });
    expect(screen.queryByText("Saved")).not.toBeInTheDocument();
  });
});
