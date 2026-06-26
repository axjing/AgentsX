import { useCallback, useEffect, useRef, useState } from "react";
import type { Message } from "./types";

const styles: Record<string, React.CSSProperties> = {
  container: {
    display: "flex",
    flexDirection: "column",
    height: "100vh",
    maxWidth: 800,
    margin: "0 auto",
    background: "#141414",
  },
  header: {
    padding: "12px 16px",
    borderBottom: "1px solid #2a2a2a",
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
  },
  title: { fontSize: 16, fontWeight: 600, margin: 0 },
  select: {
    background: "#1e1e1e",
    color: "#e0e0e0",
    border: "1px solid #333",
    borderRadius: 6,
    padding: "4px 8px",
    fontSize: 13,
  },
  messages: {
    flex: 1,
    overflowY: "auto",
    padding: "16px",
    display: "flex",
    flexDirection: "column",
    gap: 12,
  },
  userBubble: {
    alignSelf: "flex-end",
    background: "#2563eb",
    color: "#fff",
    padding: "8px 12px",
    borderRadius: 12,
    maxWidth: "70%",
    fontSize: 14,
    lineHeight: 1.5,
  },
  assistantBubble: {
    alignSelf: "flex-start",
    background: "#262626",
    padding: "8px 12px",
    borderRadius: 12,
    maxWidth: "80%",
    fontSize: 14,
    lineHeight: 1.5,
  },
  toolBubble: {
    alignSelf: "flex-start",
    background: "#1a1a2e",
    border: "1px solid #333",
    padding: "6px 10px",
    borderRadius: 8,
    fontSize: 12,
    fontFamily: "monospace",
    maxWidth: "70%",
  },
  inputArea: {
    padding: "12px 16px",
    borderTop: "1px solid #2a2a2a",
    display: "flex",
    gap: 8,
  },
  input: {
    flex: 1,
    background: "#1e1e1e",
    border: "1px solid #333",
    borderRadius: 8,
    padding: "10px 14px",
    color: "#e0e0e0",
    fontSize: 14,
    outline: "none",
  },
  sendBtn: {
    background: "#2563eb",
    color: "#fff",
    border: "none",
    borderRadius: 8,
    padding: "10px 20px",
    fontSize: 14,
    cursor: "pointer",
  },
};

function MessageBubble({ message }: { message: Message }) {
  if (message.role === "user") {
    return <div style={styles.userBubble}>{message.content}</div>;
  }
  if (message.role === "tool") {
    const name = message.name || "tool";
    return (
      <div style={styles.toolBubble}>
        <div style={{ marginBottom: 4, color: "#888" }}>{name}</div>
        {message.content.slice(0, 200)}
        {message.content.length > 200 ? "..." : ""}
      </div>
    );
  }
  return <div style={styles.assistantBubble}>{message.content}</div>;
}

export default function App() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [model, setModel] = useState("gpt-4o");
  const [loading, setLoading] = useState(false);
  const messagesEnd = useRef<HTMLDivElement>(null);

  useEffect(() => {
    messagesEnd.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const send = useCallback(async () => {
    if (!input.trim() || loading) return;
    const userMsg: Message = { role: "user", content: input };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setLoading(true);

    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          messages: [...messages, userMsg],
          model,
        }),
      });

      const reader = res.body?.getReader();
      if (!reader) return;

      let assistantText = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        const chunk = new TextDecoder().decode(value);
        assistantText += chunk;
        setMessages((prev) => {
          const last = prev[prev.length - 1];
          if (last?.role === "assistant") {
            return [...prev.slice(0, -1), { ...last, content: assistantText }];
          }
          return [...prev, { role: "assistant", content: assistantText }];
        });
      }
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: `Error: ${err}` },
      ]);
    } finally {
      setLoading(false);
    }
  }, [input, messages, model, loading]);

  const handleNewSession = () => {
    setMessages([]);
  };

  return (
    <div style={styles.container}>
      <div style={styles.header}>
        <h1 style={styles.title}>AgentsX</h1>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <select
            style={styles.select}
            value={model}
            onChange={(e) => setModel(e.target.value)}
          >
            <option value="gpt-4o">gpt-4o</option>
            <option value="gpt-4o-mini">gpt-4o-mini</option>
          </select>
          <button style={styles.sendBtn} onClick={handleNewSession}>
            New
          </button>
        </div>
      </div>

      <div style={styles.messages}>
        {messages.map((msg, i) => (
          <MessageBubble key={i} message={msg} />
        ))}
        <div ref={messagesEnd} />
      </div>

      <div style={styles.inputArea}>
        <input
          style={styles.input}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send();
            }
          }}
          placeholder="Type a message..."
        />
        <button
          style={{
            ...styles.sendBtn,
            opacity: loading || !input ? 0.5 : 1,
          }}
          onClick={send}
          disabled={loading || !input}
        >
          {loading ? "..." : "Send"}
        </button>
      </div>
    </div>
  );
}
