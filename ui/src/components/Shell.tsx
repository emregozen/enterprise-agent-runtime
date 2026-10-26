import { Bot, Database, KeyRound, LayoutDashboard, Moon, Play, Search, Settings, Sparkles, Sun } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { copy } from "../lib/copy";

const LINKS = [
  { to: "/", label: copy.navOverview, icon: LayoutDashboard, end: true, group: "operate" },
  { to: "/agents", label: copy.navAgents, icon: Bot, group: "operate" },
  { to: "/runs", label: copy.navRuns, icon: Play, group: "operate" },
  { to: "/datasources", label: copy.navSources, icon: Database, group: "configure" },
  { to: "/models", label: copy.navModels, icon: Sparkles, group: "configure" },
  { to: "/secrets", label: copy.navSecrets, icon: KeyRound, group: "configure" },
  { to: "/settings", label: copy.navSettings, icon: Settings, group: "configure" },
];

const CRUMBS: Record<string, string> = {
  "/": copy.navOverview,
  "/agents": copy.navAgents,
  "/agents/new": copy.navNewAgent,
  "/runs": copy.navRuns,
  "/datasources": copy.navSources,
  "/models": copy.navModels,
  "/secrets": copy.navSecrets,
  "/settings": copy.navSettings,
};

export function Shell() {
  const location = useLocation();
  const navigate = useNavigate();
  const [mode, setMode] = useState("…");
  const [dark, setDark] = useState(() => document.documentElement.classList.contains("dark"));
  const [palette, setPalette] = useState(() => new URLSearchParams(location.search).get("palette") === "1");
  useEffect(() => {
    api<{ llm_mode: string }>("/api/settings").then((body) => setMode(body.llm_mode)).catch(() => setMode(copy.offline));
  }, []);
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setPalette(true);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  const crumb = CRUMBS[location.pathname] || (location.pathname.startsWith("/agents/") ? "Agent" : location.pathname.startsWith("/runs/") ? "Run" : copy.console);
  function toggleTheme() {
    const next = !dark;
    setDark(next);
    document.documentElement.classList.toggle("dark", next);
    localStorage.setItem("theme", next ? "dark" : "light");
  }
  const modelLabel = mode === "fake" ? copy.fakeModel : mode === "openai" ? copy.liveModel : mode;
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <NavLink className="brand" to="/">
          <span className="mark" aria-hidden>A</span>
          <span>
            <span>Control plane</span>
            <strong>Agent <em>Runtime</em></strong>
          </span>
        </NavLink>
        <nav className="nav" aria-label="Primary">
          <div className="nav-label">{copy.navOperate}</div>
          {LINKS.filter((link) => link.group === "operate").map((link) => (
            <NavLink key={link.to} to={link.to} end={link.end} className={({ isActive }) => (isActive ? "active" : "")}>
              <link.icon size={16} aria-hidden />
              {link.label}
            </NavLink>
          ))}
          <div className="nav-label">{copy.navConfigure}</div>
          {LINKS.filter((link) => link.group === "configure").map((link) => (
            <NavLink key={link.to} to={link.to} className={({ isActive }) => (isActive ? "active" : "")}>
              <link.icon size={16} aria-hidden />
              {link.label}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-foot">
          <span className="badge info">{modelLabel}</span>
        </div>
      </aside>
      <div className="main">
        <header className="topbar">
          <div className="crumbs">{copy.console} / <b>{crumb}</b></div>
          <div className="row">
            <button className="cmdk-trigger" type="button" onClick={() => setPalette(true)}>
              <span className="row"><Search size={14} aria-hidden /> {copy.search}</span>
              <kbd>⌘K</kbd>
            </button>
            <button className="btn-ghost icon-btn" type="button" aria-label={dark ? copy.themeToLight : copy.themeToDark} onClick={toggleTheme}>
              {dark ? <Sun size={16} /> : <Moon size={16} />}
            </button>
          </div>
        </header>
        <main className="content">
          <Outlet />
        </main>
      </div>
      {palette && <CommandPalette onClose={() => setPalette(false)} onPick={(path) => { setPalette(false); navigate(path); }} onTheme={toggleTheme} dark={dark} />}
    </div>
  );
}

function CommandPalette({ onClose, onPick, onTheme, dark }: { onClose: () => void; onPick: (path: string) => void; onTheme: () => void; dark: boolean }) {
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const items = useMemo(() => {
    const base = [
      ...LINKS.map((link) => ({ label: link.label, path: link.to })),
      { label: copy.navNewAgent, path: "/agents/new" },
      { label: dark ? copy.themeToLight : copy.themeToDark, path: "theme" },
    ];
    const needle = query.trim().toLocaleLowerCase("en");
    return needle ? base.filter((item) => item.label.toLocaleLowerCase("en").includes(needle)) : base;
  }, [query, dark]);
  useEffect(() => setActive(0), [query]);
  function choose(index: number) {
    const item = items[index];
    if (!item) return;
    if (item.path === "theme") {
      onTheme();
      onClose();
      return;
    }
    onPick(item.path);
  }
  return (
    <div className="palette-back" role="presentation" onMouseDown={onClose}>
      <div className="palette" role="dialog" aria-modal="true" aria-label={copy.search} onMouseDown={(event) => event.stopPropagation()}>
        <input
          autoFocus
          placeholder={copy.commandHint}
          value={query}
          aria-label={copy.search}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Escape") onClose();
            if (event.key === "ArrowDown") { event.preventDefault(); setActive((value) => Math.min(value + 1, items.length - 1)); }
            if (event.key === "ArrowUp") { event.preventDefault(); setActive((value) => Math.max(value - 1, 0)); }
            if (event.key === "Enter") choose(active);
          }}
        />
        <ul>
          {items.length === 0 && <li className="empty">{copy.noMatches}</li>}
          {items.map((item, index) => (
            <li key={item.path + item.label}>
              <button type="button" aria-selected={index === active} onMouseEnter={() => setActive(index)} onClick={() => choose(index)}>{item.label}</button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
