import { Bot, CheckCircle2, ChevronDown, ChevronUp, Code2, Database, Plus, RotateCcw, Send, ShieldAlert, ShieldCheck, Sparkles, Table2, Trash2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Badge, CodeBlock, Markdown } from "./ui";
import { api, ApiError } from "../lib/api";
import { useAuth } from "../lib/auth";
import { copy } from "../lib/copy";
import { formatNumber, formatWhen } from "../lib/format";
import { announceError } from "../lib/notify";

export type DataSourceChoice = {
  id: string;
  name: string;
  dialect: string;
  allow_tables: string[];
  sensitivity: string;
  enabled: boolean;
};

export type ChatSessionSummary = {
  id: string;
  title: string;
  datasource_name: string;
  model_ref: string | null;
  created_at: string;
  updated_at: string;
};

export type ChatMessageItem = {
  id: string;
  session_id: string;
  ordinal: number;
  role: "user" | "assistant";
  content: string;
  sql: string | null;
  columns: string[];
  rows: Record<string, unknown>[];
  row_count: number;
  latency_ms: number | null;
  status: string;
  error: string | null;
  guard_info: {
    dialect?: string;
    tables?: string[];
    aggregate?: boolean;
    cost?: number | null;
    read_only?: boolean;
    blocked?: boolean;
  };
  follow_ups: string[];
  created_at: string;
};

type AskResponse = {
  session: ChatSessionSummary;
  user_message: ChatMessageItem;
  assistant_message: ChatMessageItem;
};

function starterPromptsFor(source: DataSourceChoice | undefined): string[] {
  if (!source) {
    return [
      "Summarize total volume and key segments",
      "Show the daily trend over the last 30 days",
      "Which segment has the highest average value?",
    ];
  }
  const tables = (source.allow_tables || []).join(" ").toLowerCase();
  if (tables.includes("emp") || tables.includes("hr") || source.name.toLowerCase().includes("hr")) {
    return [
      "Compare average salary and headcount by department",
      "Which department has the highest total compensation?",
      "Departman bazında çalışan sayısı ve ortalama maaşları karşılaştır",
    ];
  }
  return [
    "Compare total sales and transaction count by region",
    "Show the daily sales trend over the last 30 days",
    "Which region has the highest average sale amount?",
    "Bölge bazında toplam satışları ve ortalamaları karşılaştır",
  ];
}

export function ChatStudio({
  mode = "hero",
}: {
  mode?: "hero" | "workspace";
}) {
  const navigate = useNavigate();
  const { can } = useAuth();
  const [sources, setSources] = useState<DataSourceChoice[]>([]);
  const [selectedSource, setSelectedSource] = useState<string>("");
  const [sessions, setSessions] = useState<ChatSessionSummary[]>([]);
  const [activeSession, setActiveSession] = useState<ChatSessionSummary | null>(null);
  const [messages, setMessages] = useState<ChatMessageItem[]>([]);
  const [question, setQuestion] = useState("");
  const [asking, setAsking] = useState(false);
  const [expanded, setExpanded] = useState(mode === "workspace");
  const [openSqlIds, setOpenSqlIds] = useState<Record<string, boolean>>({});
  const threadEndRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    api<DataSourceChoice[]>("/api/datasources")
      .then((list) => {
        const enabled = list
          .filter((item) => item.enabled)
          .sort((a, b) => {
            const rank = (s: DataSourceChoice) =>
              s.name === "postgres-sales" ? 0 : s.dialect === "postgres" ? 1 : 2;
            return rank(a) - rank(b) || a.name.localeCompare(b.name);
          });
        setSources(enabled);
        const preferred = enabled[0];
        if (preferred) setSelectedSource((prev) => prev || preferred.name);
      })
      .catch(() => setSources([]));

    if (mode === "workspace") {
      loadSessions();
    }
  }, [mode]);

  function loadSessions() {
    api<ChatSessionSummary[]>("/api/chat/sessions?limit=25")
      .then(setSessions)
      .catch(() => setSessions([]));
  }

  async function selectSession(sessionId: string) {
    try {
      const detail = await api<ChatSessionSummary & { messages: ChatMessageItem[] }>(`/api/chat/sessions/${sessionId}`);
      setActiveSession(detail);
      setMessages(detail.messages || []);
      setExpanded(true);
      if (detail.datasource_name) {
        setSelectedSource(detail.datasource_name);
      }
    } catch (exc) {
      announceError(exc);
    }
  }

  async function removeSession(sessionId: string) {
    try {
      await api(`/api/chat/sessions/${sessionId}`, { method: "DELETE" });
      setSessions((prev) => prev.filter((item) => item.id !== sessionId));
      if (activeSession?.id === sessionId) {
        startNewSession();
      }
    } catch (exc) {
      announceError(exc);
    }
  }

  function startNewSession() {
    setActiveSession(null);
    setMessages([]);
    setQuestion("");
  }

  async function sendQuestion(rawQuestion?: string) {
    const text = (rawQuestion ?? question).trim();
    if (!text || !selectedSource || asking) return;
    setExpanded(true);
    setAsking(true);
    if (!rawQuestion) setQuestion("");

    const tempId = `temp-${Date.now()}`;
    const optimisticUser: ChatMessageItem = {
      id: tempId,
      session_id: activeSession?.id || "",
      ordinal: messages.length + 1,
      role: "user",
      content: text,
      sql: null,
      columns: [],
      rows: [],
      row_count: 0,
      latency_ms: null,
      status: "succeeded",
      error: null,
      guard_info: {},
      follow_ups: [],
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, optimisticUser]);

    try {
      const res = await api<AskResponse>("/api/chat/ask", {
        method: "POST",
        body: JSON.stringify({
          question: text,
          datasource: selectedSource,
          session_id: activeSession?.id || null,
        }),
      });
      setActiveSession(res.session);
      setMessages((prev) => [
        ...prev.filter((item) => item.id !== tempId),
        res.user_message,
        res.assistant_message,
      ]);
      if (mode === "workspace") {
        loadSessions();
      }
      setTimeout(() => {
        if (typeof threadEndRef.current?.scrollIntoView === "function") {
          threadEndRef.current.scrollIntoView({ behavior: "smooth", block: "nearest" });
        }
      }, 60);
    } catch (exc: unknown) {
      const errMsg = exc instanceof ApiError ? exc.message : "Could not complete the query.";
      const fallbackAssistant: ChatMessageItem = {
        id: `err-${Date.now()}`,
        session_id: activeSession?.id || "",
        ordinal: messages.length + 2,
        role: "assistant",
        content: `**Query failed:** ${errMsg}`,
        sql: null,
        columns: [],
        rows: [],
        row_count: 0,
        latency_ms: null,
        status: "failed",
        error: errMsg,
        guard_info: { blocked: false },
        follow_ups: [],
        created_at: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, fallbackAssistant]);
      announceError(exc);
    } finally {
      setAsking(false);
    }
  }

  function toggleSql(id: string) {
    setOpenSqlIds((prev) => ({ ...prev, [id]: !prev[id] }));
  }

  function promoteToAgent(userPrompt: string) {
    const sourceObj = sources.find((s) => s.name === selectedSource);
    const params = new URLSearchParams();
    params.set("goal", userPrompt);
    if (sourceObj) {
      params.set("datasource", sourceObj.id);
    }
    navigate(`/agents/new?${params.toString()}`);
  }

  const currentSourceObj = sources.find((item) => item.name === selectedSource);
  const prompts = starterPromptsFor(currentSourceObj);
  const isExpanded = mode === "workspace" || expanded;

  const studioCard = (
    <section
      className={`chat-studio ${mode === "workspace" ? "workspace-mode" : "hero-mode"} ${isExpanded ? "expanded" : "collapsed"}`}
    >
      <div className="chat-studio-head">
        <div className="chat-head-main">
          <div className="chat-eyebrow-row">
            <span className="chat-sparkle-badge">
              <Sparkles size={13} aria-hidden />
              {copy.chatEyebrow}
            </span>
            {!isExpanded && selectedSource && (
              <button
                type="button"
                className="chat-source-mini-pill"
                onClick={() => setExpanded(true)}
                title="Change data source"
              >
                <Database size={12} aria-hidden />
                <strong>{selectedSource}</strong>
              </button>
            )}
            <span className="chat-guard-pill">
              <ShieldCheck size={13} aria-hidden />
              {copy.chatGuardBadge}
            </span>
          </div>
          {isExpanded && (
            <>
              <h2>{activeSession ? activeSession.title : copy.chatHeroTitle}</h2>
              <p className="chat-lead">{copy.chatHeroLead}</p>
            </>
          )}
        </div>
        <div className="row">
          {messages.length > 0 && (
            <button className="btn-ghost chat-mini-btn" type="button" onClick={startNewSession}>
              <RotateCcw size={14} aria-hidden />
              {copy.chatNewSession}
            </button>
          )}
          {mode === "hero" && (
            <button
              className="btn-ghost chat-mini-btn"
              type="button"
              onClick={() => setExpanded((prev) => !prev)}
            >
              {isExpanded ? <ChevronUp size={14} aria-hidden /> : <ChevronDown size={14} aria-hidden />}
              {isExpanded ? "Minimize" : "Expand"}
            </button>
          )}
          {mode === "hero" && (
            <Link className="btn-ghost chat-mini-btn" to="/chat">
              {copy.chatFullWorkspace} →
            </Link>
          )}
        </div>
      </div>

      {isExpanded && (
        <>
          <div className="chat-source-bar" role="group" aria-label="Select data source">
            <span className="chat-source-label">
              <Database size={14} aria-hidden /> Data source:
            </span>
            <div className="chat-source-pills">
              {sources.map((src) => {
                const active = src.name === selectedSource;
                return (
                  <button
                    key={src.id}
                    type="button"
                    className={`chat-source-pill ${active ? "on" : ""}`}
                    onClick={() => setSelectedSource(src.name)}
                  >
                    <strong>{src.name}</strong>
                    <span className="dialect-tag">{src.dialect}</span>
                    {src.allow_tables?.length > 0 && (
                      <small className="tables-tag">{src.allow_tables.join(", ")}</small>
                    )}
                  </button>
                );
              })}
              {sources.length === 0 && (
                <span className="lede">No active data sources available in this group.</span>
              )}
            </div>
          </div>

          {messages.length === 0 ? (
            <div className="chat-empty-state">
              <div className="chat-starter-label">Try an instant question on <b>{selectedSource || "your data"}</b>:</div>
              <div className="chat-starter-grid">
                {prompts.map((prompt) => (
                  <button
                    key={prompt}
                    type="button"
                    className="chat-starter-chip"
                    disabled={asking || !selectedSource}
                    onClick={() => void sendQuestion(prompt)}
                  >
                    <Sparkles size={14} className="chip-icon" aria-hidden />
                    <span>{prompt}</span>
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="chat-thread" aria-live="polite">
              {messages.map((msg, index) => {
                if (msg.role === "user") {
                  return (
                    <div key={msg.id} className="chat-turn user-turn">
                      <div className="chat-user-bubble">
                        <p>{msg.content}</p>
                      </div>
                    </div>
                  );
                }
                const priorUserPrompt =
                  index > 0 && messages[index - 1]?.role === "user"
                    ? messages[index - 1].content
                    : msg.content;
                const showSql = Boolean(openSqlIds[msg.id]);
                const blocked = msg.status === "failed" || Boolean(msg.guard_info?.blocked);
                return (
                  <div key={msg.id} className="chat-turn assistant-turn">
                    <article className={`chat-assistant-card ${blocked ? "blocked" : ""}`}>
                      <header className="chat-card-meta">
                        <div className="row">
                          <Badge status={msg.status} />
                          {blocked ? (
                            <span className="badge bad">
                              <ShieldAlert size={12} aria-hidden /> {copy.chatBlockedBadge}
                            </span>
                          ) : (
                            <span className="badge ok">
                              <CheckCircle2 size={12} aria-hidden /> {copy.chatGuardBadge}
                            </span>
                          )}
                          {msg.guard_info?.tables && msg.guard_info.tables.length > 0 && (
                            <span className="badge muted">
                              <Table2 size={12} aria-hidden /> {msg.guard_info.tables.join(", ")}
                            </span>
                          )}
                          {!blocked && (
                            <span className="badge muted">
                              {formatNumber(msg.row_count)} {msg.row_count === 1 ? "row" : "rows"}
                            </span>
                          )}
                          {msg.latency_ms != null && (
                            <span className="badge muted">{formatNumber(msg.latency_ms)} ms</span>
                          )}
                        </div>
                        <div className="row">
                          {msg.sql && (
                            <button
                              type="button"
                              className="btn-ghost chat-mini-btn"
                              onClick={() => toggleSql(msg.id)}
                            >
                              <Code2 size={13} aria-hidden />
                              {showSql ? copy.chatHideSql : copy.chatViewSql}
                            </button>
                          )}
                          {!blocked && can("builder:draft") && (
                            <button
                              type="button"
                              className="btn-ghost chat-mini-btn promote-btn"
                              onClick={() => promoteToAgent(priorUserPrompt)}
                            >
                              <Bot size={13} aria-hidden />
                              {copy.chatAutomateAgent}
                            </button>
                          )}
                        </div>
                      </header>

                      <div className="chat-answer-body">
                        <Markdown text={msg.content} />
                      </div>

                      {showSql && msg.sql && (
                        <div className="chat-sql-drawer">
                          <CodeBlock code={msg.sql} />
                        </div>
                      )}

                      {msg.rows && msg.rows.length > 0 && msg.columns && msg.columns.length > 0 && (
                        <div className="chat-table-wrap">
                          <table className="data chat-data-table">
                            <thead>
                              <tr>
                                {msg.columns.map((col) => (
                                  <th key={col}>{col}</th>
                                ))}
                              </tr>
                            </thead>
                            <tbody>
                              {msg.rows.slice(0, 25).map((row, rIdx) => (
                                <tr key={rIdx}>
                                  {msg.columns.map((col) => {
                                    const val = row[col];
                                    const formatted =
                                      typeof val === "number"
                                        ? formatNumber(val)
                                        : val === null || val === undefined
                                          ? "—"
                                          : String(val);
                                    return <td key={col}>{formatted}</td>;
                                  })}
                                </tr>
                              ))}
                            </tbody>
                          </table>
                          {msg.rows.length > 25 && (
                            <div className="chat-table-foot">
                              Showing top 25 of {formatNumber(msg.rows.length)} rows (capped at 100 rows for memory safety).
                            </div>
                          )}
                        </div>
                      )}

                      {msg.follow_ups && msg.follow_ups.length > 0 && (
                        <div className="chat-followups">
                          {msg.follow_ups.map((follow) => (
                            <button
                              key={follow}
                              type="button"
                              className="chat-followup-chip"
                              disabled={asking}
                              onClick={() => void sendQuestion(follow)}
                            >
                              {follow} →
                            </button>
                          ))}
                        </div>
                      )}
                    </article>
                  </div>
                );
              })}
              {asking && (
                <div className="chat-turn assistant-turn">
                  <div className="chat-thinking-card">
                    <span className="spinner" aria-hidden />
                    <span>{copy.chatThinking}</span>
                  </div>
                </div>
              )}
              <div ref={threadEndRef} />
            </div>
          )}
        </>
      )}

      <form
        className="chat-composer"
        onSubmit={(event) => {
          event.preventDefault();
          void sendQuestion();
        }}
      >
        <input
          type="text"
          className="chat-input"
          aria-label={copy.chatPlaceholder}
          placeholder={copy.chatPlaceholder}
          value={question}
          disabled={asking || !selectedSource}
          onFocus={() => setExpanded(true)}
          onChange={(event) => setQuestion(event.target.value)}
        />
        <button
          type="submit"
          className="btn chat-send-btn"
          disabled={asking || !question.trim() || !selectedSource}
        >
          {asking ? <span className="spinner" aria-hidden /> : <Send size={15} aria-hidden />}
          {copy.chatAskButton}
        </button>
      </form>
    </section>
  );

  if (mode === "hero") {
    return studioCard;
  }

  return (
    <div className="chat-workspace-grid">
      <aside className="card chat-history-sidebar">
        <div className="row" style={{ justifyContent: "space-between", marginBottom: 12 }}>
          <h2 style={{ margin: 0 }}>{copy.chatHistoryTitle}</h2>
          <button type="button" className="btn-ghost chat-mini-btn" onClick={startNewSession}>
            <Plus size={14} aria-hidden /> {copy.chatNewSession}
          </button>
        </div>
        {sessions.length === 0 ? (
          <p className="lede" style={{ fontSize: 13 }}>{copy.chatNoHistory}</p>
        ) : (
          <ul className="chat-session-list">
            {sessions.map((item) => {
              const active = activeSession?.id === item.id;
              return (
                <li key={item.id} className={active ? "active" : ""}>
                  <button
                    type="button"
                    className="chat-session-item"
                    onClick={() => void selectSession(item.id)}
                  >
                    <strong>{item.title}</strong>
                    <small>{item.datasource_name} · {formatWhen(item.updated_at)}</small>
                  </button>
                  {can("chat:delete") && (
                    <button
                      type="button"
                      className="chat-session-del"
                      aria-label="Delete conversation"
                      onClick={() => void removeSession(item.id)}
                    >
                      <Trash2 size={13} aria-hidden />
                    </button>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </aside>
      <div>{studioCard}</div>
    </div>
  );
}
