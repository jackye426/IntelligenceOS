"use client";

import { useState, useRef, useEffect, type FormEvent } from "react";

interface Message {
  role: "user" | "assistant";
  content: string;
  sources?: { entity_type: string; entity_id: string; snippet: string }[];
}

export default function AskPage() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!query.trim() || loading) return;

    const userMessage: Message = { role: "user", content: query.trim() };
    setMessages((prev) => [...prev, userMessage]);
    setQuery("");
    setLoading(true);

    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        query: userMessage.content,
        messages: messages.map((m) => ({ role: m.role, content: m.content })),
      }),
    });

    if (res.ok) {
      const data = await res.json();
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: data.answer, sources: data.sources },
      ]);
    } else {
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: "Something went wrong. Please try again." },
      ]);
    }

    setLoading(false);
  }

  const suggestions = [
    "Which fertility clinics have unclear practitioner routing?",
    "What objections have clinics raised about AI assistants?",
    "Which clinics have WhatsApp as their primary contact route?",
    "What patient problems involve uncertainty about who to book with?",
  ];

  return (
    <>
      <header className="topbar">
        <div>
          <p className="eyebrow">Internal knowledge query</p>
          <h1>Ask DocMap</h1>
        </div>
        {messages.length > 0 && (
          <button className="text-button" onClick={() => setMessages([])}>Clear chat</button>
        )}
      </header>

      <div className="chat-layout">
        <div className="chat-messages">
          {messages.length === 0 && (
            <div style={{ display: "grid", gap: "10px", maxWidth: "560px", margin: "auto", paddingTop: "20px" }}>
              <p style={{ color: "var(--muted)", textAlign: "center", marginBottom: "16px" }}>
                Ask anything about your clinics, outreach, observations, or patient signals.
              </p>
              {suggestions.map((s) => (
                <button
                  key={s}
                  className="text-button"
                  style={{ textAlign: "left", fontSize: "13px", padding: "10px 14px" }}
                  onClick={() => { setQuery(s); }}
                >
                  {s}
                </button>
              ))}
            </div>
          )}

          {messages.map((m, i) => (
            <div key={i} className={`chat-message ${m.role}`}>
              <p style={{ margin: 0, whiteSpace: "pre-wrap" }}>{m.content}</p>
              {m.sources && m.sources.length > 0 && (
                <div className="chat-sources">
                  <span>Sources:</span>
                  {m.sources.map((s, j) => (
                    <span key={j} className="pill" title={s.snippet}>
                      {s.entity_type} {s.entity_id.slice(0, 8)}…
                    </span>
                  ))}
                </div>
              )}
            </div>
          ))}

          {loading && (
            <div className="chat-message assistant">
              <p style={{ margin: 0, color: "var(--muted)" }}>Thinking…</p>
            </div>
          )}

          <div ref={bottomRef} />
        </div>

        <form onSubmit={handleSubmit} className="chat-input-bar">
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Ask about any clinic, observation, or outreach pattern…"
            disabled={loading}
            autoFocus
          />
          <button type="submit" className="primary-button" disabled={loading || !query.trim()}>
            Send
          </button>
        </form>
      </div>
    </>
  );
}
