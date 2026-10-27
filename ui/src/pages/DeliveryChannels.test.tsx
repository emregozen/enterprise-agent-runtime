import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, vi } from "vitest";
import { DeliveryChannels } from "./DeliveryChannels";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Delivery channels", () => {
  it("shows the HTTP API fields when that type is selected", async () => {
    const user = userEvent.setup();
    vi.stubGlobal("fetch", vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => [],
    })));
    render(<DeliveryChannels />);
    expect(await screen.findByRole("heading", { name: "Delivery channels" })).toBeInTheDocument();
    await user.click(screen.getAllByRole("button", { name: "New channel" })[0]);
    await user.click(screen.getByRole("button", { name: "Channel type" }));
    await user.click(screen.getByRole("option", { name: /HTTP API/ }));
    expect(screen.getByRole("textbox", { name: "URL" })).toBeInTheDocument();
    expect((screen.getByRole("textbox", { name: "Body template" }) as HTMLTextAreaElement).value).toContain("{{to}}");
    expect(screen.getByRole("textbox", { name: "Headers" })).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "Host" })).not.toBeInTheDocument();
  });
});
