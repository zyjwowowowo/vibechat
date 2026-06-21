"use client";

import {
  Activity, ArrowLeft, ArrowRight, Bot, Check, ChevronRight, CircleAlert,
  Compass, DoorOpen, History, Home as HomeIcon, LoaderCircle, LockKeyhole,
  LogOut, Menu, MessageCircleHeart, Send, Settings, ShieldCheck, Sparkles,
  Trash2, UserRound, Users, Waves, X,
} from "lucide-react";
import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import SplatScene from "./components/SplatScene";

const API_URL = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");
const TOKEN_KEY = "vibechat_session_token";

type View = "home" | "discover" | "memory" | "settings" | "chat";
type Session = { token: string; user_id: string; nickname: string; avatar_seed: string; email?: string; is_guest: boolean };
type Emotion = {
  id: string; primary_emotion: string; distribution: Record<string, number>;
  valence: number; arousal: number; intensity: number; keywords: string[];
  explanation: string; safety_level: "normal" | "concern" | "crisis"; degraded: boolean;
};
type Match = { ticket_id: string; status: string; conversation_id?: string; match_score?: number; waited_seconds: number; mode: string };
type Message = { id: string; sender_name: string; role: string; content: string; sequence: number; created_at: string; is_self: boolean };
type Conversation = {
  id: string; kind: string; status: string; emotion_label: string; match_score?: number; summary?: string;
  participants: { nickname: string; avatar_seed: string; is_ai: boolean; is_self: boolean }[]; messages: Message[];
};
type Room = { id: string; conversation_id: string; slug: string; title: string; emotion_label: string; description: string; member_count: number; joined: boolean };
type EmotionHistory = { id: string; primary_emotion: string; intensity: number; valence: number; arousal: number; explanation: string; created_at: string };
type ConversationHistory = { id: string; kind: string; emotion_label: string; status: string; created_at: string; summary?: string; peer_names: string[] };
type MatchMode = "similar" | "complementary" | "public_room" | "private_group";

const emotionLooks: Record<string, { color: string; soft: string; mark: string; line: string }> = {
  喜悦: { color: "#D6A75F", soft: "#F8EDD6", mark: "✦", line: "光线正在从身体里慢慢浮起来" },
  平静: { color: "#2E6F6A", soft: "#DDEBE8", mark: "≈", line: "水面没有停止，只是波纹变得很轻" },
  期待: { color: "#5689A6", soft: "#DDEAF0", mark: "↗", line: "你正在向尚未发生的事靠近" },
  孤独: { color: "#65788F", soft: "#E2E7EC", mark: "○", line: "想被看见，也想保留自己的边界" },
  悲伤: { color: "#55758D", soft: "#DCE7ED", mark: "◌", line: "有些重量需要被允许缓慢下沉" },
  焦虑: { color: "#8577C9", soft: "#E8E4F5", mark: "⌁", line: "许多念头正在争夺同一片空间" },
  愤怒: { color: "#F08E7F", soft: "#F9E1DD", mark: "△", line: "边界正在发出需要被听见的信号" },
  疲惫: { color: "#89796F", soft: "#EBE5E1", mark: "…", line: "身心都在请求一次真正的停靠" },
};

const matchModes: { id: MatchMode; title: string; eyebrow: string; copy: string; icon: typeof Users }[] = [
  { id: "similar", title: "相似情绪", eyebrow: "一对一", copy: "遇见一位情绪光谱相近的人，不必从解释自己开始。", icon: Waves },
  { id: "complementary", title: "互补情绪", eyebrow: "一对一", copy: "寻找能让当下稍微松动的另一种能量，而不是简单的相反。", icon: Activity },
  { id: "public_room", title: "同频房间", eyebrow: "公开", copy: "进入持续开放的情绪空间，先旁听，也可以慢慢加入。", icon: DoorOpen },
  { id: "private_group", title: "多人聊天室", eyebrow: "3–6 人", copy: "组成一次私密的小型相遇，只有本次匹配成员可见。", icon: Users },
];

function Avatar({ seed, ai = false }: { seed: string; ai?: boolean }) {
  const glyphs = ["潮", "雾", "昼", "岛"];
  const index = [...seed].reduce((sum, item) => sum + item.charCodeAt(0), 0) % glyphs.length;
  return <span className={`avatar avatar-${index}`}>{ai ? <Bot size={16} /> : glyphs[index]}</span>;
}

export default function Home() {
  const [view, setView] = useState<View>("home");
  const [transitioning, setTransitioning] = useState(false);
  const [mobileNav, setMobileNav] = useState(false);
  const [session, setSession] = useState<Session | null>(null);
  const [text, setText] = useState("");
  const [emotion, setEmotion] = useState<Emotion | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [match, setMatch] = useState<Match | null>(null);
  const [conversation, setConversation] = useState<Conversation | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [draft, setDraft] = useState("");
  const [rooms, setRooms] = useState<Room[]>([]);
  const [emotionHistory, setEmotionHistory] = useState<EmotionHistory[]>([]);
  const [conversationHistory, setConversationHistory] = useState<ConversationHistory[]>([]);
  const [authOpen, setAuthOpen] = useState(false);
  const [authMode, setAuthMode] = useState<"register" | "login">("register");
  const [authEmail, setAuthEmail] = useState("");
  const [authPassword, setAuthPassword] = useState("");
  const [authBusy, setAuthBusy] = useState(false);
  const [error, setError] = useState("");
  const [assist, setAssist] = useState<{ kind: string; suggestion: string } | null>(null);
  const [assistBusy, setAssistBusy] = useState("");
  const wsRef = useRef<WebSocket | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

  const apiFetch = useCallback(async <T,>(path: string, options: RequestInit = {}, tokenOverride?: string): Promise<T> => {
    const token = tokenOverride ?? session?.token ?? localStorage.getItem(TOKEN_KEY) ?? "";
    const response = await fetch(`${API_URL}${path}`, {
      ...options,
      headers: { "Content-Type": "application/json", ...(token ? { "X-Session-Token": token } : {}), ...(options.headers || {}) },
    });
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.detail || "连接暂时走神了，请再试一次");
    }
    return response.json();
  }, [session?.token]);

  useEffect(() => {
    const boot = async () => {
      const saved = localStorage.getItem(TOKEN_KEY);
      if (saved) {
        try { setSession(await apiFetch<Session>("/api/v1/sessions/me", {}, saved)); return; }
        catch { localStorage.removeItem(TOKEN_KEY); }
      }
      try {
        const fresh = await apiFetch<Session>("/api/v1/sessions", { method: "POST" }, "");
        localStorage.setItem(TOKEN_KEY, fresh.token); setSession(fresh);
      } catch (cause) { setError(cause instanceof Error ? cause.message : "无法创建访客身份"); }
    };
    void boot();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const navigate = useCallback((next: View) => {
    setMobileNav(false);
    if (next === view) return;
    if (view === "home" && !window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      setTransitioning(true);
      window.setTimeout(() => { setView(next); setTransitioning(false); }, 1040);
    } else setView(next);
  }, [view]);

  const loadRooms = useCallback(async () => {
    try { setRooms(await apiFetch<Room[]>("/api/v1/rooms")); } catch { /* discovery remains usable */ }
  }, [apiFetch]);

  const loadHistory = useCallback(async () => {
    if (!session || session.is_guest) return;
    try {
      const [emotions, conversations] = await Promise.all([
        apiFetch<EmotionHistory[]>("/api/v1/me/emotions"), apiFetch<ConversationHistory[]>("/api/v1/me/conversations"),
      ]);
      setEmotionHistory(emotions); setConversationHistory(conversations);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "回顾暂时无法载入"); }
  }, [apiFetch, session]);

  useEffect(() => { if (view === "discover") void loadRooms(); if (view === "memory") void loadHistory(); }, [view, loadRooms, loadHistory]);

  const analyze = async (event: FormEvent) => {
    event.preventDefault(); if (!session || text.trim().length < 2) return;
    setError(""); setAnalyzing(true);
    try {
      const result = await apiFetch<Emotion>("/api/v1/emotions/analyze", { method: "POST", body: JSON.stringify({ text: text.trim() }) });
      setEmotion(result); setAnalyzing(false);
      window.setTimeout(() => navigate("discover"), 220);
    } catch (cause) { setAnalyzing(false); setError(cause instanceof Error ? cause.message : "情绪分析没有完成"); }
  };

  const submitAuth = async (event: FormEvent) => {
    event.preventDefault(); setAuthBusy(true); setError("");
    try {
      const data = await apiFetch<Session>(`/api/v1/auth/${authMode}`, {
        method: "POST", body: JSON.stringify({ email: authEmail, password: authPassword, guest_token: session?.is_guest ? session.token : undefined, device_name: "网页端" }),
      }, session?.token || "");
      localStorage.setItem(TOKEN_KEY, data.token); setSession(data); setAuthOpen(false); setAuthPassword("");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "账户操作没有完成"); }
    finally { setAuthBusy(false); }
  };

  const openConversation = useCallback(async (id: string) => {
    try {
      const data = await apiFetch<Conversation>(`/api/v1/conversations/${id}`);
      setConversation(data); setMessages(data.messages); setView("chat");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "无法进入这段对话"); }
  }, [apiFetch]);

  const selectMode = async (mode: MatchMode) => {
    if (!emotion) { navigate("home"); return; }
    if (session?.is_guest) { setAuthMode("register"); setAuthOpen(true); return; }
    if (mode === "public_room") { document.getElementById("room-list")?.scrollIntoView({ behavior: "smooth" }); return; }
    setError("");
    try {
      const data = await apiFetch<Match>("/api/v1/matches", { method: "POST", body: JSON.stringify({ emotion_id: emotion.id, mode }) });
      setMatch(data); if (data.conversation_id) await openConversation(data.conversation_id);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "匹配没有开始"); }
  };

  useEffect(() => {
    if (!match || match.conversation_id || match.status !== "waiting") return;
    const timer = window.setInterval(async () => {
      try {
        const data = await apiFetch<Match>(`/api/v1/matches/${match.ticket_id}`); setMatch(data);
        if (data.conversation_id) { window.clearInterval(timer); await openConversation(data.conversation_id); }
      } catch { window.clearInterval(timer); }
    }, 1200);
    return () => window.clearInterval(timer);
  }, [match, apiFetch, openConversation]);

  const joinRoom = async (room: Room) => {
    if (session?.is_guest) { setAuthOpen(true); return; }
    try {
      const data = await apiFetch<Conversation>(`/api/v1/rooms/${room.id}/join`, { method: "POST" });
      setConversation(data); setMessages(data.messages); setView("chat");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "没有进入房间"); }
  };

  const chooseFallback = async (choice: "continue" | "direct" | "ai") => {
    if (!match) return;
    try {
      const data = await apiFetch<Match>(`/api/v1/matches/${match.ticket_id}/fallback`, {
        method: "POST", body: JSON.stringify({ choice }),
      });
      setMatch(data); if (data.conversation_id) await openConversation(data.conversation_id);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "没有切换匹配方式"); }
  };

  useEffect(() => {
    if (view !== "chat" || !conversation || !session) return;
    let closed = false; let retry = 0;
    const connect = () => {
      const socket = new WebSocket(`${API_URL.replace(/^http/, "ws")}/api/v1/ws/conversations/${conversation.id}`, ["vibechat", `token.${session.token}`]);
      wsRef.current = socket;
      socket.onmessage = (event) => {
        const payload = JSON.parse(event.data);
        if (payload.type === "message.created") {
          const incoming = { ...payload.message, is_self: payload.message.sender_name === session.nickname };
          setMessages((current) => current.some((item) => item.id === incoming.id) ? current : [...current, incoming]);
        }
      };
      socket.onclose = () => { if (!closed) retry = window.setTimeout(connect, 1600); };
    };
    connect(); return () => { closed = true; window.clearTimeout(retry); wsRef.current?.close(); };
  }, [view, conversation, session]);

  useEffect(() => endRef.current?.scrollIntoView({ behavior: "smooth" }), [messages]);

  const send = async (event: FormEvent) => {
    event.preventDefault(); const content = draft.trim(); if (!content || !conversation) return; setDraft("");
    if (wsRef.current?.readyState === WebSocket.OPEN) wsRef.current.send(JSON.stringify({ type: "message", content }));
    else {
      try { const item = await apiFetch<Message>(`/api/v1/conversations/${conversation.id}/messages`, { method: "POST", body: JSON.stringify({ content }) }); setMessages((items) => [...items, item]); }
      catch { setDraft(content); }
    }
  };

  const requestAssist = async (kind: string) => {
    if (!conversation) return; setAssistBusy(kind);
    try {
      const result = await apiFetch<{ kind: string; suggestion: string }>(`/api/v1/conversations/${conversation.id}/assist`, {
        method: "POST", body: JSON.stringify({ kind, draft }),
      }); setAssist(result);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "AI 建议没有生成"); }
    finally { setAssistBusy(""); }
  };

  const logout = async () => {
    try { await apiFetch("/api/v1/auth/logout", { method: "POST" }); } catch { /* local sign out still completes */ }
    localStorage.removeItem(TOKEN_KEY); setSession(null); window.location.reload();
  };

  const look = emotionLooks[emotion?.primary_emotion || "平静"];
  const distribution = useMemo(() => Object.entries(emotion?.distribution || {}).sort((a, b) => b[1] - a[1]).slice(0, 4), [emotion]);

  return (
    <main className={`weatherApp view-${view} ${transitioning ? "pageDiving" : ""}`} style={{ "--emotion": look.color, "--emotion-soft": look.soft } as React.CSSProperties}>
      {view === "home" ? (
        <>
          <header className="landingHeader">
            <button className="brand" onClick={() => navigate("home")}><span><Waves size={17} /></span>VibeChat</button>
            <nav><button onClick={() => navigate("discover")}>发现</button><button onClick={() => navigate("memory")}>情绪回顾</button></nav>
            <button className="identityPill" onClick={() => session?.is_guest ? setAuthOpen(true) : navigate("settings")}><i />{session?.is_guest ? "保存我的情绪" : session?.nickname || "载入中"}</button>
          </header>
          <section className="landingGrid">
            <div className={`heroCopy ${analyzing ? "isAnalyzing" : ""}`}>
              <div className="weatherLabel"><span>此刻情绪气象</span><b>可见度 · 正在形成</b></div>
              <h1>先感受自己，<br /><em>再遇见别人。</em></h1>
              <p>不急着把情绪说对。写下此刻正在发生的事，我们会把它变成一张可以被理解的天气图。</p>
              <form className="weatherInput" onSubmit={analyze}>
                <textarea value={text} onChange={(event) => setText(event.target.value.slice(0, 800))} placeholder="今天发生了什么？哪怕只是一个说不清的感觉……" aria-label="写下此刻的情绪" />
                <div><span><b style={{ width: `${Math.min(100, text.length / 3.2)}%` }} />{text.length}/800</span><button disabled={!session || text.trim().length < 2 || analyzing}>{analyzing ? <><LoaderCircle className="spin" size={16} />正在显影</> : <>让情绪显影 <ArrowRight size={16} /></>}</button></div>
              </form>
              <div className="trustLine"><span><ShieldCheck size={14} />原文不会分享给陌生人</span><span><LockKeyhole size={14} />访客记录 24 小时后消散</span></div>
            </div>
            <SplatScene transitioning={transitioning} emotionColor={look.color} inputEnergy={Math.min(1, text.length / 180)} />
          </section>
          <footer className="landingFoot"><span>SCROLL TO FEEL</span><p>情绪不是标签，而是一片不断变化的场。</p><span>SHANGHAI · {new Date().getFullYear()}</span></footer>
        </>
      ) : (
        <div className="productShell">
          <aside className={mobileNav ? "navOpen" : ""}>
            <div className="sideTop"><button className="brand" onClick={() => navigate("home")}><span><Waves size={17} /></span>VibeChat</button><button className="navClose" onClick={() => setMobileNav(false)}><X /></button></div>
            <nav>
              <button onClick={() => navigate("home")}><HomeIcon />写下此刻</button>
              <button className={view === "discover" ? "active" : ""} onClick={() => navigate("discover")}><Compass />发现同频</button>
              <button className={view === "memory" ? "active" : ""} onClick={() => navigate("memory")}><History />情绪回顾</button>
              <button className={view === "settings" ? "active" : ""} onClick={() => navigate("settings")}><Settings />账户设置</button>
            </nav>
            <div className="sideIdentity"><Avatar seed={session?.avatar_seed || "guest"} /><div><strong>{session?.nickname || "载入中"}</strong><span>{session?.is_guest ? "访客模式" : session?.email}</span></div><ChevronRight size={15} /></div>
          </aside>
          <section className="pageArea">
            <header className="mobileHeader"><button onClick={() => setMobileNav(true)}><Menu /></button><span>VibeChat</span><Avatar seed={session?.avatar_seed || "guest"} /></header>

            {view === "discover" && <DiscoverPage emotion={emotion} look={look} distribution={distribution} match={match} rooms={rooms} onMode={selectMode} onRoom={joinRoom} onFallback={chooseFallback} onHome={() => navigate("home")} />}
            {view === "memory" && <MemoryPage guest={session?.is_guest ?? true} emotions={emotionHistory} conversations={conversationHistory} onLogin={() => setAuthOpen(true)} onOpen={openConversation} onClear={async () => { await apiFetch("/api/v1/me/history", { method: "DELETE" }); await loadHistory(); }} />}
            {view === "settings" && <SettingsPage session={session} onLogin={() => setAuthOpen(true)} onLogout={logout} />}
            {view === "chat" && conversation && <ChatPage conversation={conversation} messages={messages} draft={draft} setDraft={setDraft} onSend={send} onBack={() => navigate("discover")} onAssist={requestAssist} assistBusy={assistBusy} assist={assist} setAssist={setAssist} endRef={endRef} />}
          </section>
        </div>
      )}

      {error && <div className="errorToast"><CircleAlert size={16} /><span>{error}</span><button onClick={() => setError("")}><X size={15} /></button></div>}
      {authOpen && <AuthModal mode={authMode} setMode={setAuthMode} email={authEmail} setEmail={setAuthEmail} password={authPassword} setPassword={setAuthPassword} busy={authBusy} onSubmit={submitAuth} onClose={() => setAuthOpen(false)} />}
      <div className="transitionCurtain"><span>正在进入情绪深处</span><i /></div>
    </main>
  );
}

function DiscoverPage({ emotion, look, distribution, match, rooms, onMode, onRoom, onFallback, onHome }: {
  emotion: Emotion | null; look: { color: string; soft: string; mark: string; line: string }; distribution: [string, number][]; match: Match | null; rooms: Room[];
  onMode: (mode: MatchMode) => void; onRoom: (room: Room) => void; onFallback: (choice: "continue" | "direct" | "ai") => void; onHome: () => void;
}) {
  return <div className="contentPage discoverPage">
    <div className="pageHeading"><div><span className="kicker">DISCOVER / 情绪导航</span><h2>{emotion ? "选择这次相遇的方式" : "先让此刻被看见"}</h2><p>{emotion ? "没有哪一种匹配更正确，只有此刻更适合你的距离。" : "完成一次情绪显影后，我们会为你打开不同的相遇入口。"}</p></div><button className="softButton" onClick={onHome}>{emotion ? "重新表达" : "写下心情"}<ArrowRight size={15} /></button></div>
    {emotion ? <section className="emotionReport">
      <div className="emotionSeal" style={{ background: look.soft, color: look.color }}><span>{look.mark}</span><b>{emotion.primary_emotion}</b><small>{Math.round(emotion.intensity * 100)}% 强度</small></div>
      <div className="reportText"><span>你的情绪天气</span><h3>“{emotion.explanation}”</h3><p>{look.line}</p><div className="keywordRow">{emotion.keywords.map((word) => <i key={word}>#{word}</i>)}</div></div>
      <div className="spectrumMini">{distribution.map(([name, value]) => <div key={name}><span>{name}</span><i><b style={{ width: `${value * 100}%` }} /></i><strong>{Math.round(value * 100)}</strong></div>)}</div>
    </section> : <section className="emptyWeather"><Waves /><p>情绪场还没有读数</p></section>}
    <section className="modeSection"><div className="sectionLabel"><span>匹配策略</span><b>由你决定靠近的方式</b></div><div className="modeGrid">{matchModes.map((mode) => <button key={mode.id} onClick={() => onMode(mode.id)} disabled={!emotion}><span><mode.icon /></span><i>{mode.eyebrow}</i><h3>{mode.title}</h3><p>{mode.copy}</p><b>选择此模式 <ArrowRight /></b></button>)}</div></section>
    {match?.status === "waiting" && <div className="matchingStrip"><LoaderCircle className="spin" /><span><b>{match.mode === "private_group" ? "正在组成一间私密小组" : "正在寻找合适的回应"}</b><small>已经等待 {match.waited_seconds || 0} 秒，请让页面保持打开</small></span></div>}
    {match?.status === "needs_choice" && <div className="fallbackChoice"><span><b>目前还没有凑齐三个人</b><small>不用困在等待里，换一种靠近方式也可以。</small></span><div><button onClick={() => onFallback("continue")}>继续等等</button><button onClick={() => onFallback("direct")}>改为一对一</button><button onClick={() => onFallback("ai")}>先和 AI 聊聊</button></div></div>}
    <section className="roomSection" id="room-list"><div className="sectionLabel"><span>公开同频房</span><b>先旁听，也可以慢慢开口</b></div><div className="roomList">{rooms.map((room) => <button key={room.id} onClick={() => onRoom(room)}><i style={{ background: emotionLooks[room.emotion_label]?.soft || "#E4EBEA", color: emotionLooks[room.emotion_label]?.color || "#2E6F6A" }}>{emotionLooks[room.emotion_label]?.mark || "≈"}</i><span><small>{room.emotion_label} · {room.member_count} 人来过</small><strong>{room.title}</strong><p>{room.description}</p></span><ArrowRight /></button>)}</div></section>
  </div>;
}

function MemoryPage({ guest, emotions, conversations, onLogin, onOpen, onClear }: { guest: boolean; emotions: EmotionHistory[]; conversations: ConversationHistory[]; onLogin: () => void; onOpen: (id: string) => void; onClear: () => void }) {
  const max = Math.max(...emotions.slice(0, 12).map((item) => item.intensity), 1);
  if (guest) return <div className="contentPage lockedPage"><div className="lockIllustration"><History /><i /></div><span className="kicker">MEMORY / 情绪回顾</span><h2>把走过的情绪，<br />留成一张自己的地图。</h2><p>登录后可以跨设备保存情绪轨迹、完整对话和 AI 回顾。陌生人仍然只会看到你的匿名身份。</p><button className="primaryAction" onClick={onLogin}>保存我的情绪 <ArrowRight /></button></div>;
  return <div className="contentPage memoryPage">
    <div className="pageHeading"><div><span className="kicker">MEMORY / 情绪回顾</span><h2>你的情绪并不是一条直线</h2><p>回看变化，不是为了给自己打分，而是发现那些已经走过的地方。</p></div><button className="dangerGhost" onClick={onClear}><Trash2 />清空历史</button></div>
    <section className="trajectoryCard"><div><span>最近的情绪轨迹</span><b>{emotions.length} 次被记录的此刻</b></div><div className="chart">{emotions.slice(0, 12).reverse().map((item) => <i key={item.id} style={{ height: `${24 + item.intensity / max * 70}%`, background: emotionLooks[item.primary_emotion]?.color }} title={`${item.primary_emotion} ${Math.round(item.intensity * 100)}%`} />)}</div><div className="chartLegend"><span>较早</span><span>现在</span></div></section>
    <div className="memoryColumns"><section><div className="sectionLabel"><span>情绪记录</span><b>{emotions.length}</b></div>{emotions.length ? <div className="timeline">{emotions.slice(0, 8).map((item) => <article key={item.id}><i style={{ background: emotionLooks[item.primary_emotion]?.color }} /><time>{new Date(item.created_at).toLocaleDateString("zh-CN", { month: "short", day: "numeric" })}</time><div><strong>{item.primary_emotion} · {Math.round(item.intensity * 100)}%</strong><p>{item.explanation}</p></div></article>)}</div> : <p className="emptyCopy">下一次表达会从这里开始形成轨迹。</p>}</section>
      <section><div className="sectionLabel"><span>对话回顾</span><b>{conversations.length}</b></div>{conversations.length ? <div className="historyList">{conversations.slice(0, 8).map((item) => <button key={item.id} onClick={() => onOpen(item.id)}><span><small>{item.kind === "public_room" ? "公开房间" : item.kind === "private_group" ? "私密小组" : "匿名对话"}</small><strong>{item.peer_names.join("、") || item.emotion_label}</strong><p>{item.summary || `围绕「${item.emotion_label}」的一次相遇`}</p></span><ChevronRight /></button>)}</div> : <p className="emptyCopy">完成一段对话后，可以在这里生成回顾。</p>}</section></div>
  </div>;
}

function SettingsPage({ session, onLogin, onLogout }: { session: Session | null; onLogin: () => void; onLogout: () => void }) {
  return <div className="contentPage settingsPage"><span className="kicker">ACCOUNT / 账户设置</span><h2>让记录属于你，<br />身份继续留在雾里。</h2><section className="profileCard"><Avatar seed={session?.avatar_seed || "guest"} /><div><small>当前匿名身份</small><strong>{session?.nickname || "访客"}</strong><p>{session?.is_guest ? "尚未绑定账户，本次记录将在 24 小时后消散。" : `已通过 ${session?.email} 跨设备保存`}</p></div>{session?.is_guest ? <button onClick={onLogin}>绑定账户</button> : <Check />}</section><section className="settingList"><div><span><ShieldCheck />陌生人看到什么</span><p>只看到匿名昵称、头像和本次共享的情绪标签，永远不会看到邮箱与原始输入。</p></div><div><span><LockKeyhole />历史如何保存</span><p>{session?.is_guest ? "访客数据保存 24 小时。" : "情绪、对话和摘要持续保存，直到你主动删除。"}</p></div></section>{!session?.is_guest && <button className="logoutButton" onClick={onLogout}><LogOut />退出当前设备</button>}</div>;
}

function ChatPage({ conversation, messages, draft, setDraft, onSend, onBack, onAssist, assistBusy, assist, setAssist, endRef }: { conversation: Conversation; messages: Message[]; draft: string; setDraft: (value: string) => void; onSend: (event: FormEvent) => void; onBack: () => void; onAssist: (kind: string) => void; assistBusy: string; assist: { kind: string; suggestion: string } | null; setAssist: (value: { kind: string; suggestion: string } | null) => void; endRef: React.RefObject<HTMLDivElement | null> }) {
  const peers = conversation.participants.filter((item) => !item.is_self);
  const tools = [{ id: "opening", label: "帮我开口" }, { id: "gentle_rewrite", label: "温和表达" }, { id: "icebreaker", label: "破冰问题" }, { id: "summary", label: "生成回顾" }];
  return <div className="chatPage"><header><button onClick={onBack}><ArrowLeft /></button><div><span>{conversation.kind === "public_room" ? "公开同频房" : conversation.kind === "private_group" ? "私密多人聊天室" : "匿名对话"}</span><strong>{peers.map((item) => item.nickname).join("、") || conversation.emotion_label}</strong></div><i>{conversation.emotion_label}</i></header><div className="chatLayout"><section className="messagePanel"><div className="privacyNote"><LockKeyhole />原始情绪和账户身份不会分享给其他成员</div><div className="messages">{messages.map((message) => <article className={message.is_self ? "self" : "peer"} key={message.id}>{!message.is_self && <Avatar seed={message.sender_name} ai={message.role === "ai"} />}<div><small>{message.is_self ? "我" : message.sender_name}</small><p>{message.content}</p><time>{new Date(message.created_at).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}</time></div></article>)}<div ref={endRef} /></div>{assist && <div className="assistDraft"><span><Sparkles />仅你可见的建议<button onClick={() => setAssist(null)}><X /></button></span><p>{assist.suggestion}</p>{assist.kind !== "summary" && <button onClick={() => { setDraft(assist.suggestion); setAssist(null); }}>放入输入框</button>}</div>}<form className="composer" onSubmit={onSend}><textarea value={draft} onChange={(event) => setDraft(event.target.value.slice(0, 1000))} placeholder="从一句真实但不完整的话开始……" rows={1} /><button disabled={!draft.trim()} aria-label="发送"><Send /></button></form></section><aside className="aiRail"><span><Bot />私密对话助手</span><p>建议只会显示给你，发送前仍由你决定。</p>{tools.map((tool) => <button key={tool.id} onClick={() => onAssist(tool.id)} disabled={Boolean(assistBusy)}>{assistBusy === tool.id ? <LoaderCircle className="spin" /> : <Sparkles />}<span>{tool.label}</span><ChevronRight /></button>)}</aside></div></div>;
}

function AuthModal({ mode, setMode, email, setEmail, password, setPassword, busy, onSubmit, onClose }: { mode: "register" | "login"; setMode: (mode: "register" | "login") => void; email: string; setEmail: (value: string) => void; password: string; setPassword: (value: string) => void; busy: boolean; onSubmit: (event: FormEvent) => void; onClose: () => void }) {
  return <div className="modalShade" role="dialog" aria-modal="true" aria-label="账户登录"><div className="authModal"><button className="modalClose" onClick={onClose}><X /></button><span className="authMark"><UserRound /></span><small>{mode === "register" ? "保存这次情绪" : "欢迎回到这里"}</small><h2>{mode === "register" ? "让记录在不同设备间继续" : "登录你的私密情绪空间"}</h2><p>邮箱不会展示给其他用户，你仍会以匿名身份参与匹配。</p><form onSubmit={onSubmit}><label>邮箱<input type="email" value={email} onChange={(event) => setEmail(event.target.value)} required /></label><label>密码<input type="password" value={password} onChange={(event) => setPassword(event.target.value)} minLength={8} required placeholder="至少 8 位" /></label><button disabled={busy}>{busy ? <LoaderCircle className="spin" /> : mode === "register" ? "创建账户并保存" : "登录"}<ArrowRight /></button></form><button className="authSwitch" onClick={() => setMode(mode === "register" ? "login" : "register")}>{mode === "register" ? "已有账户？登录" : "还没有账户？注册"}</button></div></div>;
}
