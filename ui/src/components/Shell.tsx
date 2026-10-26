import { Bot, Database, KeyRound, LayoutDashboard, Play, Settings, Sparkles } from "lucide-react";
import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { api } from "../lib/api";

const LINKS = [
  { to: "/", label: "Genel Bakış", icon: LayoutDashboard, end: true },
  { to: "/agents", label: "Agent'lar", icon: Bot },
  { to: "/runs", label: "Koşumlar", icon: Play },
  { to: "/datasources", label: "Veri Kaynakları", icon: Database },
  { to: "/models", label: "LLM Modelleri", icon: Sparkles },
  { to: "/secrets", label: "Gizli Bilgi Kaynakları", icon: KeyRound },
  { to: "/settings", label: "Ayarlar", icon: Settings },
];

const CRUMBS: Record<string, string> = {
  "/": "Genel Bakış",
  "/agents": "Agent'lar",
  "/agents/new": "Yeni ajan",
  "/runs": "Koşumlar",
  "/datasources": "Veri Kaynakları",
  "/models": "LLM Modelleri",
  "/secrets": "Gizli Bilgi Kaynakları",
  "/settings": "Ayarlar",
};

export function Shell() {
  const location = useLocation();
  const [mode, setMode] = useState("…");
  const [dark, setDark] = useState(() => document.documentElement.classList.contains("dark"));
  useEffect(() => {
    api<{ llm_mode: string }>("/api/settings").then((body) => setMode(body.llm_mode)).catch(() => setMode("çevrimdışı"));
  }, []);
  const crumb = CRUMBS[location.pathname] || (location.pathname.startsWith("/agents/") ? "Ajan" : location.pathname.startsWith("/runs/") ? "Koşum" : "Konsol");
  function toggleTheme() {
    const next = !dark;
    setDark(next);
    document.documentElement.classList.toggle("dark", next);
    localStorage.setItem("theme", next ? "dark" : "light");
  }
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <span>Kontrol</span>
          <strong>Ajan Çalıştırıcı</strong>
        </div>
        <nav className="nav" aria-label="Ana menü">
          {LINKS.map((link) => (
            <NavLink key={link.to} to={link.to} end={link.end} className={({ isActive }) => (isActive ? "active" : "")}>
              <link.icon size={16} aria-hidden />
              {link.label}
            </NavLink>
          ))}
        </nav>
      </aside>
      <div className="main">
        <header className="topbar">
          <div className="crumbs">Konsol / <b>{crumb}</b></div>
          <div className="row">
            <span className="badge info">{mode === "fake" ? "Sahte model" : mode === "openai" ? "Canlı model" : mode}</span>
            <button className="btn-ghost" type="button" onClick={toggleTheme}>{dark ? "Aydınlık" : "Karanlık"}</button>
          </div>
        </header>
        <main className="content">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
