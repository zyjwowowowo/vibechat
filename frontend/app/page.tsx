"use client";

import {
  ArrowLeft,
  ArrowRight,
  Bot,
  Check,
  CircleAlert,
  Clock3,
  HeartHandshake,
  LoaderCircle,
  LockKeyhole,
  MessageCircleHeart,
  RefreshCw,
  Send,
  ShieldCheck,
  Sparkles,
  Users,
  Waves,
} from "lucide-react";
import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";

const API_URL = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");
const TOKEN_KEY = "vibechat_session_token";

type Screen = "input" | "analyzing" | "result" | "matching" | "chat";
type Session = { token: string; user_id: string; nickname: string; avatar_seed: string };
type Emotion = {
  id: string;
  primary_emotion: string;
  distribution: Record<string, number>;
  valence: number;
  arousal: number;
  intensity: number;
  keywords: string[];
  explanation: string;
  safety_level: "normal" | "concern" | "crisis";
  degraded: boolean;
};
type Match = {
  ticket_id: string;
  status: string;
  conversation_id?: string;
  match_score?: number;
  waited_seconds: number;
};
type ChatMessage = {
  id: string;
  sender_name: string;
  role: string;
  content: string;
  sequence: number;
  created_at: string;
  is_self: boolean;
};
type Conversation = {
  id: string;
  kind: "human" | "ai";
  status: string;
  emotion_label: string;
  match_score?: number;
  participants: { nickname: string; avatar_seed: string; is_ai: boolean; is_self: boolean }[];
  messages: ChatMessage[];
};

const emotionLooks: Record<string, { color: string; soft: string; emoji: string; copy: string }> = {
  喜悦: { color: "#ffbf69", soft: "#fff2d9", emoji: "✦", copy: "像一束刚刚亮起的光" },
  平静: { color: "#79cdb9", soft: "#dff7ef", emoji: "≈", copy: "像风停在柔软的水面" },
  期待: { color: "#82a9ff", soft: "#e4ecff", emoji: "↗", copy: "正向尚未发生的事靠近" },
  孤独: { color: "#8e9cc5", soft: "#e7eaf5", emoji: "○", copy: "想被看见，也想被理解" },
  悲伤: { color: "#7ea4c9", soft: "#e1edf7", emoji: "◌", copy: "有些重量正在缓慢下沉" },
  焦虑: { color: "#b18add", soft: "#eee2fa", emoji: "⌁", copy: "许多念头同时涌了上来" },
  愤怒: { color: "#ed806e", soft: "#fde5df", emoji: "△", copy: "边界正在提醒你保护自己" },
  疲惫: { color: "#a18f83", soft: "#efe9e5", emoji: "…", copy: "身心都在请求一次停靠" },
};

function apiErrorMessage(error: unknown) {
  return error instanceof Error ? error.message : "刚才的连接走神了，请再试一次";
}

function Avatar({ seed, ai = false, large = false }: { seed: string; ai?: boolean; large?: boolean }) {
  const palettes = [
    ["#7165e8", "#ada5ff"],
    ["#4e9b88", "#9bdecb"],
    ["#cf725f", "#ffb9a8"],
    ["#5684b9", "#a8c9ef"],
  ];
  const index = [...seed].reduce((sum, char) => sum + char.charCodeAt(0), 0) % palettes.length;
  return (
    <div
      className={`avatar ${large ? "avatarLarge" : ""}`}
      style={{ background: `linear-gradient(145deg, ${palettes[index][0]}, ${palettes[index][1]})` }}
    >
      {ai ? <Bot size={large ? 26 : 18} /> : <span>{["水", "风", "月", "云"][index]}</span>}
    </div>
  );
}

export default function Home() {
  const [screen, setScreen] = useState<Screen>("input");
  const [session, setSession] = useState<Session | null>(null);
  const [text, setText] = useState("");
  const [emotion, setEmotion] = useState<Emotion | null>(null);
  const [match, setMatch] = useState<Match | null>(null);
  const [conversation, setConversation] = useState<Conversation | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState("");
  const [peerTyping, setPeerTyping] = useState(false);
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const chatEndRef = useRef<HTMLDivElement | null>(null);

  const apiFetch = useCallback(async <T,>(path: string, options: RequestInit = {}, overrideToken?: string): Promise<T> => {
    const token = overrideToken || session?.token || localStorage.getItem(TOKEN_KEY) || "";
    const response = await fetch(`${API_URL}${path}`, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...(token ? { "X-Session-Token": token } : {}),
        ...(options.headers || {}),
      },
    });
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.detail || "服务暂时没有回应");
    }
    return response.json();
  }, [session?.token]);

  useEffect(() => {
    const bootstrap = async () => {
      const saved = localStorage.getItem(TOKEN_KEY);
      if (saved) {
        try {
          setSession(await apiFetch<Session>("/api/v1/sessions/me", {}, saved));
          return;
        } catch {
          localStorage.removeItem(TOKEN_KEY);
        }
      }
      try {
        const fresh = await apiFetch<Session>("/api/v1/sessions", { method: "POST" }, "");
        localStorage.setItem(TOKEN_KEY, fresh.token);
        setSession(fresh);
      } catch (err) {
        setError(`无法创建匿名身份：${apiErrorMessage(err)}`);
      }
    };
    bootstrap();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const analyze = async (event: FormEvent) => {
    event.preventDefault();
    if (!session || text.trim().length < 2) return;
    setError("");
    setScreen("analyzing");
    try {
      const result = await apiFetch<Emotion>("/api/v1/emotions/analyze", {
        method: "POST",
        body: JSON.stringify({ text: text.trim() }),
      });
      setEmotion(result);
      setScreen("result");
    } catch (err) {
      setError(apiErrorMessage(err));
      setScreen("input");
    }
  };

  const openConversation = useCallback(async (conversationId: string) => {
    try {
      const data = await apiFetch<Conversation>(`/api/v1/conversations/${conversationId}`);
      setConversation(data);
      setMessages(data.messages);
      setScreen("chat");
    } catch (err) {
      setError(apiErrorMessage(err));
    }
  }, [apiFetch]);

  const startMatching = async () => {
    if (!emotion?.id) return;
    setError("");
    setScreen("matching");
    try {
      const data = await apiFetch<Match>("/api/v1/matches", {
        method: "POST",
        body: JSON.stringify({ emotion_id: emotion.id }),
      });
      setMatch(data);
      if (data.conversation_id) await openConversation(data.conversation_id);
    } catch (err) {
      setError(apiErrorMessage(err));
      setScreen("result");
    }
  };

  useEffect(() => {
    if (screen !== "matching" || !match?.ticket_id) return;
    const timer = window.setInterval(async () => {
      try {
        const data = await apiFetch<Match>(`/api/v1/matches/${match.ticket_id}`);
        setMatch(data);
        if (data.conversation_id) {
          window.clearInterval(timer);
          await openConversation(data.conversation_id);
        }
      } catch (err) {
        setError(apiErrorMessage(err));
      }
    }, 1000);
    return () => window.clearInterval(timer);
  }, [apiFetch, match?.ticket_id, openConversation, screen]);

  useEffect(() => {
    if (screen !== "chat" || !conversation || !session) return;
    let retryTimer: number | undefined;
    let closedByEffect = false;
    const connect = () => {
      const socketBase = API_URL.replace(/^http/, "ws");
      const ws = new WebSocket(
        `${socketBase}/api/v1/ws/conversations/${conversation.id}`,
        ["vibechat", `token.${session.token}`],
      );
      wsRef.current = ws;
      ws.onopen = () => setConnected(true);
      ws.onclose = () => {
        setConnected(false);
        if (!closedByEffect) retryTimer = window.setTimeout(connect, 1800);
      };
      ws.onmessage = (event) => {
        const payload = JSON.parse(event.data);
        if (payload.type === "message.created") {
          const incoming = { ...payload.message, is_self: payload.message.sender_name === session.nickname };
          setMessages((current) => current.some((item) => item.id === incoming.id) ? current : [...current, incoming]);
          setPeerTyping(false);
        }
        if (payload.type === "typing") setPeerTyping(Boolean(payload.active));
      };
    };
    connect();
    return () => {
      closedByEffect = true;
      if (retryTimer) window.clearTimeout(retryTimer);
      wsRef.current?.close();
    };
  }, [conversation, screen, session]);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, peerTyping]);

  const sendMessage = async (event: FormEvent) => {
    event.preventDefault();
    const content = draft.trim();
    if (!content || !conversation) return;
    setDraft("");
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: "message", content }));
      return;
    }
    try {
      const message = await apiFetch<ChatMessage>(`/api/v1/conversations/${conversation.id}/messages`, {
        method: "POST",
        body: JSON.stringify({ content }),
      });
      setMessages((current) => current.some((item) => item.id === message.id) ? current : [...current, message]);
    } catch (err) {
      setDraft(content);
      setError(apiErrorMessage(err));
    }
  };

  const reset = () => {
    wsRef.current?.close();
    setText("");
    setEmotion(null);
    setMatch(null);
    setConversation(null);
    setMessages([]);
    setError("");
    setScreen("input");
  };

  const look = emotionLooks[emotion?.primary_emotion || "平静"];
  const peer = conversation?.participants.find((item) => !item.is_self);
  const sortedEmotions = useMemo(
    () => Object.entries(emotion?.distribution || {}).sort((a, b) => b[1] - a[1]).slice(0, 3),
    [emotion],
  );

  return (
    <main className={`app app-${screen}`} style={{ "--emotion": look.color, "--emotion-soft": look.soft } as React.CSSProperties}>
      <div className="ambient ambientOne" />
      <div className="ambient ambientTwo" />
      <header className="topbar">
        <button className="brand" onClick={reset} aria-label="回到首页">
          <span className="brandMark"><Waves size={18} /></span>
          <span>VibeChat</span>
        </button>
        <div className="topMeta">
          <span className="privacy"><LockKeyhole size={13} /> 24h 后消散</span>
          {session && <span className="identity"><i />{session.nickname}</span>}
        </div>
      </header>

      {error && (
        <div className="errorToast"><CircleAlert size={16} />{error}<button onClick={() => setError("")}>×</button></div>
      )}

      {screen === "input" && (
        <section className="hero shell">
          <div className="eyebrow"><Sparkles size={14} /> AI 驱动的情绪社交</div>
          <h1>此刻的你，<br /><em>是什么颜色？</em></h1>
          <p className="lead">不需要整理好情绪。写下正在发生的事，我们会读懂其中的色彩，带你遇见一位同频的陌生人。</p>
          <form className="emotionForm" onSubmit={analyze}>
            <textarea
              value={text}
              onChange={(event) => setText(event.target.value.slice(0, 800))}
              placeholder="比如：今天做完了一个拖了很久的项目，明明应该开心，却突然觉得有点空……"
              aria-label="描述你此刻的心情"
            />
            <div className="formBottom">
              <span>{text.length}<small>/800</small></span>
              <button className="primaryButton" disabled={!session || text.trim().length < 2}>
                感受我的情绪 <ArrowRight size={17} />
              </button>
            </div>
          </form>
          <div className="trustRow">
            <span><ShieldCheck size={16} /> 匿名表达</span>
            <span><Users size={16} /> 同频匹配</span>
            <span><MessageCircleHeart size={16} /> 温柔相遇</span>
          </div>
        </section>
      )}

      {screen === "analyzing" && (
        <section className="centerStage shell">
          <div className="emotionOrb analyzingOrb"><span /><span /><span /><Sparkles size={30} /></div>
          <div className="eyebrow">正在感受你的文字</div>
          <h2>让情绪慢慢显影…</h2>
          <p>AI 正在理解语气、强度与藏在句子之间的情绪。</p>
          <div className="analysisSteps">
            <span className="done"><Check size={13} /> 捕捉情绪线索</span>
            <span className="active"><LoaderCircle size={13} /> 描绘情绪色彩</span>
            <span><Users size={13} /> 寻找同频的人</span>
          </div>
        </section>
      )}

      {screen === "result" && emotion && (
        <section className="result shell">
          <button className="backButton" onClick={() => setScreen("input")}><ArrowLeft size={16} />重新表达</button>
          <div className="resultGrid">
            <div className="emotionVisual">
              <div className="bigOrb"><span>{look.emoji}</span></div>
              <div className="tinyLabel">你的主情绪</div>
              <h2>{emotion.primary_emotion}</h2>
              <p>{look.copy}</p>
            </div>
            <div className="emotionCard">
              <div className="cardTop"><span>情绪光谱</span>{emotion.degraded && <b>温和降级分析</b>}</div>
              <h3>“{emotion.explanation}”</h3>
              <div className="spectrum">
                {sortedEmotions.map(([name, value]) => (
                  <div className="spectrumRow" key={name}>
                    <span>{name}</span><div><i style={{ width: `${Math.max(value * 100, 4)}%` }} /></div><strong>{Math.round(value * 100)}%</strong>
                  </div>
                ))}
              </div>
              <div className="metrics">
                <div><span>情绪强度</span><strong>{Math.round(emotion.intensity * 100)}</strong></div>
                <div><span>内在波动</span><strong>{Math.round(emotion.arousal * 100)}</strong></div>
                <div><span>情绪倾向</span><strong>{emotion.valence > 0.2 ? "向暖" : emotion.valence < -0.2 ? "向内" : "平衡"}</strong></div>
              </div>
              <div className="keywords">{emotion.keywords.map((word) => <span key={word}>#{word}</span>)}</div>
            </div>
          </div>
          {emotion.safety_level !== "normal" && (
            <div className="safetyCard">
              <HeartHandshake size={22} />
              <div><strong>你不必独自扛着这些</strong><p>如果你正处于立即危险中，请联系当地急救服务或身边可信任的人。VibeChat 不是医疗服务，但会陪你找到下一步支持。</p></div>
            </div>
          )}
          <div className="resultAction">
            <div><Users size={18} /><span><strong>准备寻找同频的人</strong><small>只分享情绪色彩，不会展示你的原文</small></span></div>
            <button className="primaryButton" onClick={startMatching}>开始同频匹配 <ArrowRight size={17} /></button>
          </div>
        </section>
      )}

      {screen === "matching" && emotion && (
        <section className="centerStage matching shell">
          <div className="matchScene">
            <div className="personOrb me"><Avatar seed={session?.avatar_seed || "me"} large /></div>
            <div className="signal"><i /><i /><i /></div>
            <div className="personOrb unknown"><span>?</span></div>
          </div>
          <div className="eyebrow"><LoaderCircle className="spin" size={14} /> 正在寻找同频的人</div>
          <h2>把你的「{emotion.primary_emotion}」<br />送向另一颗相似的心</h2>
          <p>正在比较情绪光谱、强度和内在波动，而不只是一个标签。</p>
          <div className="waitPill"><Clock3 size={14} /> 已等待 {match?.waited_seconds || 0} 秒</div>
          <div className="fallbackNote"><Bot size={15} /> 10 秒内没有遇见真人，AI 匿名旅伴会来接住这次表达</div>
          <button className="textButton" onClick={reset}>先离开这里</button>
        </section>
      )}

      {screen === "chat" && conversation && peer && (
        <section className="chatShell shell">
          <div className="chatHeader">
            <div className="peerInfo">
              <Avatar seed={peer.avatar_seed} ai={peer.is_ai} />
              <div><strong>{peer.nickname}</strong><span><i className={connected ? "online" : ""} />{connected ? "同频连接中" : "正在重连"}</span></div>
            </div>
            <div className="matchBadge">
              {conversation.kind === "ai" ? <><Bot size={14} /> AI 旅伴</> : <><Waves size={14} /> 同频度 {Math.round((conversation.match_score || 0) * 100)}%</>}
            </div>
            <button className="leaveButton" onClick={reset}>结束相遇</button>
          </div>
          <div className="chatContext">
            <span style={{ background: look.soft, color: look.color }}>{look.emoji}</span>
            你们因相似的「{conversation.emotion_label}」在此刻相遇
          </div>
          <div className="messageList">
            <div className="systemMessage"><LockKeyhole size={12} /> 这是匿名对话。原始心情和真实身份不会分享给对方。</div>
            {conversation.kind === "ai" && messages.length === 0 && (
              <div className="aiIntro"><Bot size={18} /><span><strong>月光水獭是明确标注的 AI 旅伴</strong>它不会冒充真人，也不会提供医疗诊断。先和它说一句此刻最想说的话吧。</span></div>
            )}
            {messages.map((message) => (
              <div className={`messageRow ${message.is_self ? "self" : "peer"}`} key={message.id}>
                {!message.is_self && <Avatar seed={peer.avatar_seed} ai={message.role === "ai"} />}
                <div className="bubbleWrap">
                  {!message.is_self && <span>{message.sender_name}</span>}
                  <div className="bubble">{message.content}</div>
                  <time>{new Date(message.created_at).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}</time>
                </div>
              </div>
            ))}
            {peerTyping && <div className="typing"><i /><i /><i /></div>}
            <div ref={chatEndRef} />
          </div>
          <form className="composer" onSubmit={sendMessage}>
            <textarea
              rows={1}
              value={draft}
              placeholder="说点什么，让此刻被听见…"
              onChange={(event) => {
                setDraft(event.target.value.slice(0, 1000));
                wsRef.current?.send(JSON.stringify({ type: "typing", active: Boolean(event.target.value) }));
              }}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  event.currentTarget.form?.requestSubmit();
                }
              }}
            />
            <button disabled={!draft.trim()} aria-label="发送消息"><Send size={18} /></button>
          </form>
          <div className="chatFoot">保持善意，不追问身份 · 会话将在 24 小时后消散</div>
        </section>
      )}

      <footer className="footer"><span>VibeChat</span><span>让每一种情绪，都有被听见的可能</span></footer>
    </main>
  );
}
