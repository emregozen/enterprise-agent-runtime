import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { Select, type SelectOption } from "./Select";

function Harness({ options, initial = "a" }: { options: SelectOption[]; initial?: string }) {
  const [value, setValue] = useState(initial);
  return <Select ariaLabel="Status" value={value} onChange={setValue} options={options} />;
}

const FEW: SelectOption[] = [
  { value: "a", label: "Alpha", description: "First", icon: <span data-testid="alpha-icon">A</span> },
  { value: "b", label: "Beta", description: "Second" },
  { value: "c", label: "Gamma", description: "Third" },
];

const MANY: SelectOption[] = Array.from({ length: 8 }, (_, index) => ({
  value: String(index + 1),
  label: `Option ${index + 1}`,
}));

describe("Select", () => {
  it("opens a listbox and selects with the arrow keys and Enter", async () => {
    const user = userEvent.setup();
    render(<Harness options={FEW} />);
    const trigger = screen.getByRole("button", { name: "Status" });
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    await user.click(trigger);
    const list = screen.getByRole("listbox", { name: "Status" });
    expect(list).toHaveAttribute("aria-activedescendant");
    const alpha = screen.getByRole("option", { name: /Alpha/ });
    expect(alpha).toHaveAttribute("aria-selected", "true");
    expect(screen.getByTestId("alpha-icon")).toBeInTheDocument();
    expect(alpha.querySelector("svg")).not.toBeNull();
    expect(screen.getByRole("option", { name: /Beta/ }).querySelector("svg")).toBeNull();
    await user.keyboard("{ArrowDown}{Enter}");
    expect(trigger).toHaveTextContent("Beta");
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });

  it("closes on Escape and returns focus to the trigger", async () => {
    const user = userEvent.setup();
    render(<Harness options={FEW} />);
    const trigger = screen.getByRole("button", { name: "Status" });
    await user.click(trigger);
    expect(screen.getByRole("listbox")).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it("jumps to a matching option as you type", async () => {
    const user = userEvent.setup();
    render(<Harness options={FEW} />);
    await user.click(screen.getByRole("button", { name: "Status" }));
    await user.keyboard("g");
    expect(screen.getByRole("option", { name: /Gamma/ })).toHaveClass("on");
  });

  it("filters when there are more than seven options", async () => {
    const user = userEvent.setup();
    render(<Harness options={MANY} initial="1" />);
    await user.click(screen.getByRole("button", { name: "Status" }));
    const filter = screen.getByRole("combobox", { name: "Filter Status" });
    await user.type(filter, "option 8");
    expect(screen.getAllByRole("option")).toHaveLength(1);
    expect(screen.getByRole("option", { name: "Option 8" })).toBeInTheDocument();
    await user.keyboard("{Enter}");
    expect(screen.getByRole("button", { name: "Status" })).toHaveTextContent("Option 8");
  });
});
