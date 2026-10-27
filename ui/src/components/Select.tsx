import { Check, ChevronDown } from "lucide-react";
import { useEffect, useId, useMemo, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { copy } from "../lib/copy";

export type SelectOption = {
  value: string;
  label: string;
  description?: string;
  icon?: ReactNode;
};

export function Select({
  value,
  onChange,
  options,
  ariaLabel,
  placeholder = copy.select,
  disabled = false,
  className = "",
}: {
  value: string;
  onChange: (value: string) => void;
  options: SelectOption[];
  ariaLabel: string;
  placeholder?: string;
  disabled?: boolean;
  className?: string;
}) {
  const uid = useId();
  const listId = `${uid}-list`;
  const buttonRef = useRef<HTMLButtonElement>(null);
  const listRef = useRef<HTMLUListElement>(null);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const [query, setQuery] = useState("");
  const [typed, setTyped] = useState("");
  const [box, setBox] = useState({ top: 0, left: 0, width: 0, maxHeight: 320 });
  const searchable = options.length > 7;
  const selected = options.find((option) => option.value === value);
  const shown = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase("en");
    if (!searchable || !needle) return options;
    return options.filter((option) => `${option.label} ${option.description ?? ""}`.toLocaleLowerCase("en").includes(needle));
  }, [options, query, searchable]);
  const activeId = shown[active] ? `${uid}-opt-${active}` : undefined;

  function place() {
    const rect = buttonRef.current?.getBoundingClientRect();
    if (!rect) return;
    const below = window.innerHeight - rect.bottom - 16;
    setBox({
      top: rect.bottom + 6,
      left: rect.left,
      width: Math.max(rect.width, 220),
      maxHeight: Math.max(180, Math.min(360, below)),
    });
  }

  function openList() {
    if (disabled) return;
    const index = Math.max(0, options.findIndex((option) => option.value === value));
    setActive(index);
    setQuery("");
    setTyped("");
    place();
    setOpen(true);
  }

  function closeList() {
    setOpen(false);
    buttonRef.current?.focus();
  }

  function choose(option: SelectOption) {
    onChange(option.value);
    setOpen(false);
    buttonRef.current?.focus();
  }

  useEffect(() => {
    if (!open) return;
    if (!searchable) listRef.current?.focus();
    function onPointer(event: MouseEvent) {
      const target = event.target as Node;
      if (buttonRef.current?.contains(target)) return;
      if ((target as Element).closest?.("[data-select-popover]")) return;
      setOpen(false);
    }
    function onReposition() { place(); }
    window.addEventListener("mousedown", onPointer);
    window.addEventListener("resize", onReposition);
    window.addEventListener("scroll", onReposition, true);
    return () => {
      window.removeEventListener("mousedown", onPointer);
      window.removeEventListener("resize", onReposition);
      window.removeEventListener("scroll", onReposition, true);
    };
  }, [open, searchable]);

  useEffect(() => {
    if (!open) return;
    document.getElementById(`${uid}-opt-${active}`)?.scrollIntoView?.({ block: "nearest" });
  }, [open, active, uid, shown.length]);

  useEffect(() => {
    if (!typed) return;
    const timer = window.setTimeout(() => setTyped(""), 700);
    const match = shown.findIndex((option) => option.label.toLocaleLowerCase("en").startsWith(typed));
    if (match >= 0) setActive(match);
    return () => window.clearTimeout(timer);
  }, [typed, shown]);

  function onListKey(event: React.KeyboardEvent) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActive((index) => Math.min(index + 1, Math.max(shown.length - 1, 0)));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActive((index) => Math.max(index - 1, 0));
    } else if (event.key === "Home") {
      event.preventDefault();
      setActive(0);
    } else if (event.key === "End") {
      event.preventDefault();
      setActive(Math.max(shown.length - 1, 0));
    } else if (event.key === "Enter") {
      event.preventDefault();
      const option = shown[active];
      if (option) choose(option);
    } else if (event.key === "Escape") {
      event.preventDefault();
      closeList();
    } else if (!searchable && event.key.length === 1 && /\S/.test(event.key)) {
      setTyped((current) => (current + event.key).toLocaleLowerCase("en"));
    }
  }

  return (
    <div className={`select ${className}`.trim()}>
      <button
        ref={buttonRef}
        type="button"
        className="select-trigger"
        aria-label={ariaLabel}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={listId}
        disabled={disabled}
        onClick={() => (open ? setOpen(false) : openList())}
        onKeyDown={(event) => {
          if (event.key === "ArrowDown" || event.key === "ArrowUp" || event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            if (!open) openList();
          }
        }}
      >
        <span>{selected?.label || placeholder}</span>
        <ChevronDown size={16} aria-hidden />
      </button>
      {open && createPortal(
        <div
          className="select-pop"
          data-select-popover
          style={{ top: box.top, left: box.left, width: box.width, maxHeight: box.maxHeight }}
          onKeyDown={onListKey}
        >
          {searchable && (
            <input
              className="select-search"
              value={query}
              placeholder={copy.filter}
              aria-label={`${copy.filter} ${ariaLabel}`}
              role="combobox"
              aria-expanded={open}
              aria-controls={listId}
              aria-activedescendant={activeId}
              aria-autocomplete="list"
              autoFocus
              onChange={(event) => { setQuery(event.target.value); setActive(0); }}
            />
          )}
          <ul
            id={listId}
            ref={listRef}
            role="listbox"
            aria-label={ariaLabel}
            aria-activedescendant={activeId}
            tabIndex={searchable ? -1 : 0}
          >
            {shown.length === 0 && <li className="select-empty">{copy.noMatches}</li>}
            {shown.map((option, index) => (
              <li key={`${option.value}:${option.label}`} role="presentation">
                <button
                  type="button"
                  role="option"
                  id={`${uid}-opt-${index}`}
                  aria-selected={option.value === value}
                  className={index === active ? "on" : ""}
                  onMouseEnter={() => setActive(index)}
                  onClick={() => choose(option)}
                >
                  <span className="select-option">
                    {option.icon}
                    <span>
                      <strong>{option.label}</strong>
                      {option.description && <small>{option.description}</small>}
                    </span>
                  </span>
                  {option.value === value && <Check size={16} aria-hidden />}
                </button>
              </li>
            ))}
          </ul>
        </div>,
        document.body,
      )}
    </div>
  );
}
