"""
dashboard.py — JARVIS Mainframe HUD v3.0
Memory-efficient, Voice-enabled, Glassmorphism UI
Run: streamlit run dashboard.py
"""
import streamlit as st
import json, os, gc, datetime, time, io, tempfile
import psutil
import requests

# ── Page Config ─────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="J.A.R.V.I.S. — Mainframe HUD",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed"
)

BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
USAGE_LOG     = os.path.join(BASE_DIR, "usage_log.jsonl")
HEALTH_LOG    = os.path.join(BASE_DIR, "system_health.log")
CHAT_ARCHIVE  = os.path.join(BASE_DIR, "chat_archive.jsonl")
SERVER        = "http://localhost:8000"
MAX_CHAT_RAM  = 10        # messages kept in session state
RAM_WARN_PCT  = 40.0      # trigger warning above this %

# ── Session State Init ───────────────────────────────────────────────────────
if "messages" not in st.session_state:
    st.session_state.messages = []
if "last_vision" not in st.session_state:
    st.session_state.last_vision = None
if "last_gc" not in st.session_state:
    st.session_state.last_gc = time.time()

# ── Memory Governance Helpers ─────────────────────────────────────────────────
def run_gc():
    gc.collect()
    st.session_state.last_gc = time.time()

def prune_and_archive_chat():
    """Keep only last MAX_CHAT_RAM messages in RAM; archive rest to disk."""
    msgs = st.session_state.messages
    if len(msgs) > MAX_CHAT_RAM:
        overflow = msgs[:-MAX_CHAT_RAM]
        with open(CHAT_ARCHIVE, "a", encoding="utf-8") as f:
            for m in overflow:
                f.write(json.dumps(m) + "\n")
        st.session_state.messages = msgs[-MAX_CHAT_RAM:]
        run_gc()

def check_ram_warning():
    ram = psutil.virtual_memory()
    if ram.percent > RAM_WARN_PCT:
        st.cache_data.clear()
        run_gc()
        return True, ram.percent
    return False, ram.percent

# ── Cached Data Fetchers ───────────────────────────────────────────────────────
@st.cache_data(persist="disk", ttl=300)
def fetch_status():
    try:
        r = requests.get(f"{SERVER}/status", timeout=3)
        return r.json()
    except Exception:
        return {"status": "OFFLINE", "message": "Cannot reach mainframe."}

@st.cache_data(ttl=5)
def get_metrics():
    cpu  = psutil.cpu_percent()
    ram  = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    return cpu, ram.percent, disk.free // (1024**3)

@st.cache_data(persist="disk", ttl=300)
def cached_ask(query: str, user_id: str = "Dwijas") -> str:
    try:
        r = requests.post(f"{SERVER}/ask_jarvis",
                          json={"user_id": user_id, "text": query}, timeout=30)
        return r.json().get("answer", "No response.")
    except Exception as e:
        return f"Mainframe unreachable: {e}"

@st.cache_data(ttl=30)
def read_health_log(n: int = 8):
    if not os.path.exists(HEALTH_LOG): return []
    with open(HEALTH_LOG, encoding="utf-8") as f:
        lines = f.readlines()
    return [l.strip() for l in lines[-n:] if l.strip()]

@st.cache_data(ttl=30)
def read_top_commands(n: int = 5):
    if not os.path.exists(USAGE_LOG): return []
    entries = []
    with open(USAGE_LOG, encoding="utf-8") as f:
        for line in f:
            try: entries.append(json.loads(line))
            except: pass
    from collections import Counter
    return Counter(e["query"] for e in entries if e.get("outcome") in ("ok","ws_ok","voice_ok")).most_common(n)

# ── CSS ─────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Rajdhani:wght@300;500;700&family=Orbitron:wght@700;900&display=swap');

html, body, [data-testid="stAppViewContainer"] {
    background: radial-gradient(ellipse at 20% 50%, #040d1a 0%, #020408 70%) !important;
    color: #c8f0ff; font-family:'Rajdhani',sans-serif;
}
[data-testid="stHeader"]  { background: transparent !important; }
[data-testid="stSidebar"] { background: rgba(0,20,40,0.9) !important; }

.hud-title {
    font-family:'Orbitron',monospace; font-size:2rem; font-weight:900;
    background:linear-gradient(90deg,#00d4ff,#00ff88,#00d4ff);
    background-size:200% auto; -webkit-background-clip:text;
    -webkit-text-fill-color:transparent;
    animation:shimmer 3s linear infinite; text-align:center; letter-spacing:.12em;
}
@keyframes shimmer { to { background-position:200% center; } }

.glass {
    background:rgba(0,180,255,0.05);
    border:1px solid rgba(0,200,255,0.18);
    border-radius:14px; padding:16px;
    backdrop-filter:blur(10px);
    box-shadow:0 0 18px rgba(0,200,255,0.07), inset 0 0 16px rgba(0,0,0,0.3);
    margin-bottom:12px;
}
.sec { font-family:'Orbitron',monospace; font-size:.78rem; color:#00d4ff;
       letter-spacing:.18em; text-transform:uppercase;
       border-bottom:1px solid rgba(0,200,255,0.18); padding-bottom:5px; margin-bottom:10px; }
.mbox { background:rgba(0,200,255,0.06); border:1px solid rgba(0,200,255,0.12);
        border-radius:8px; padding:10px 14px; margin:5px 0; }
.mlabel { color:#7ec8e3; font-size:.72rem; letter-spacing:.1em; text-transform:uppercase; }
.mval   { color:#00ffff; font-size:1.5rem; font-weight:700; font-family:'Orbitron',monospace; }
.logline { font-size:.72rem; color:#7ec8e3; border-bottom:1px solid rgba(0,200,255,0.07); padding:3px 0; }
.logerr  { font-size:.72rem; color:#ff6b6b; border-bottom:1px solid rgba(255,100,100,0.1); padding:3px 0; }

/* Arc Reactor */
.arc-wrap { display:flex; justify-content:center; padding:12px 0; }
.arc {
    width:110px; height:110px; border-radius:50%;
    background:radial-gradient(circle,#00ffff 0%,#0066cc 40%,#001133 70%);
    box-shadow:0 0 22px #00ffff,0 0 45px #00aaff,0 0 80px rgba(0,150,255,.4);
    animation:pulse 2s ease-in-out infinite; position:relative;
}
.arc::before { content:''; position:absolute; inset:14px; border-radius:50%;
               border:2px solid rgba(0,255,255,.6); animation:spin 4s linear infinite; }
.arc::after  { content:''; position:absolute; inset:28px; border-radius:50%;
               background:rgba(0,200,255,.5); box-shadow:0 0 10px #00ffff; }
@keyframes pulse { 0%,100%{box-shadow:0 0 22px #00ffff,0 0 45px #00aaff}
                   50%     {box-shadow:0 0 38px #00ffff,0 0 80px #00aaff,0 0 120px rgba(0,200,255,.6)} }
@keyframes spin  { to{transform:rotate(360deg)} }

/* Chat bubbles */
.you  { color:#00ff88; font-weight:600; font-size:.88rem; }
.jarv { color:#c8f0ff; font-size:.85rem; margin-bottom:8px; line-height:1.4; }
.ts   { color:rgba(0,200,255,.4); font-size:.68rem; }

/* RAM warning */
.ramwarn { background:rgba(255,80,80,0.1); border:1px solid rgba(255,80,80,0.4);
           border-radius:8px; padding:10px; color:#ff8080; font-size:.82rem; margin-bottom:8px; }

/* Staus dot */
.dot-on  {display:inline-block;width:9px;height:9px;border-radius:50%;background:#00ff88;box-shadow:0 0 7px #00ff88;margin-right:5px;}
.dot-off {display:inline-block;width:9px;height:9px;border-radius:50%;background:#ff4444;box-shadow:0 0 7px #ff4444;margin-right:5px;}
</style>
""", unsafe_allow_html=True)

# ── Header ───────────────────────────────────────────────────────────────────
st.markdown('<div class="hud-title">J.A.R.V.I.S. — MAINFRAME HUD</div>', unsafe_allow_html=True)
now_str  = datetime.datetime.now().strftime("%A, %d %B %Y  %H:%M:%S IST")
status_d = fetch_status()
online   = status_d.get("status") == "JARVIS ONLINE"
dot      = "on" if online else "off"
st.markdown(
    f'<p style="text-align:center;color:#7ec8e3;font-size:.8rem;letter-spacing:.08em;">'
    f'<span class="dot-{dot}"></span>{now_str} &nbsp;|&nbsp; {status_d.get("message","")}</p>',
    unsafe_allow_html=True
)

# ── RAM check (top-level so warning always shows) ────────────────────────────
ram_warn, ram_pct = check_ram_warning()
if ram_warn:
    st.markdown(f'<div class="ramwarn">⚠️ RAM at {ram_pct:.1f}% — exceeded 40% threshold. Caches cleared automatically.</div>',
                unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════════════════════
# 3-COLUMN LAYOUT
# ═══════════════════════════════════════════════════════════════════════════════
col_l, col_c, col_r = st.columns([1, 1.3, 1])

# ─────────────────────────────────────────────────────────────────────────────
# LEFT — System Health
# ─────────────────────────────────────────────────────────────────────────────
with col_l:
    st.markdown('<div class="glass">', unsafe_allow_html=True)
    st.markdown('<div class="sec">⚙ System Health</div>', unsafe_allow_html=True)

    cpu, ram_p, disk_free = get_metrics()
    st.markdown(f"""
    <div class="mbox"><div class="mlabel">CPU</div><div class="mval">{cpu:.1f}%</div></div>
    <div class="mbox"><div class="mlabel">RAM Used</div><div class="mval">{ram_p:.1f}%</div></div>
    <div class="mbox"><div class="mlabel">Disk Free</div><div class="mval">{disk_free} GB</div></div>
    """, unsafe_allow_html=True)

    s = status_d
    if online:
        st.markdown(f"""
        <div class="mbox">
          <div class="mlabel">Uptime</div><div class="mval" style="font-size:1rem">{s.get('uptime','?')}</div>
        </div>
        <div class="mbox">
          <div class="mlabel">Docs / Chunks / Vectors</div>
          <div class="mval" style="font-size:1rem">{s.get('documents',0)} / {s.get('chunks',0)} / {s.get('vectors',0)}</div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown('<div class="sec" style="margin-top:12px">🔧 Health Log</div>', unsafe_allow_html=True)
    for line in reversed(read_health_log()):
        css = "logerr" if any(w in line.lower() for w in ["fail","error","crash"]) else "logline"
        st.markdown(f'<div class="{css}">{line}</div>', unsafe_allow_html=True)

    st.markdown('</div>', unsafe_allow_html=True)

    # Quick commands shortcut panel
    st.markdown('<div class="glass">', unsafe_allow_html=True)
    st.markdown('<div class="sec">⚡ Quick Commands</div>', unsafe_allow_html=True)
    top_cmds = read_top_commands()
    if top_cmds:
        for cmd, count in top_cmds:
            label = cmd[:38] + ("…" if len(cmd) > 38 else "")
            if st.button(f"▶ {label} ({count}×)", key=f"quick_{cmd[:20]}", use_container_width=True):
                answer = cached_ask(cmd)
                ts = datetime.datetime.now().strftime("%H:%M:%S")
                st.session_state.messages.append({"role":"you","text":cmd,"ts":ts})
                st.session_state.messages.append({"role":"jarvis","text":answer,"ts":ts})
                prune_and_archive_chat()
                st.rerun()
    else:
        st.markdown('<div class="logline">Ask 3× to create shortcuts, Sir.</div>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# CENTER — Arc Reactor + Voice Core + Chat
# ─────────────────────────────────────────────────────────────────────────────
with col_c:
    # Arc Reactor
    st.markdown('<div class="glass" style="text-align:center">', unsafe_allow_html=True)
    st.markdown('<div class="arc-wrap"><div class="arc"></div></div>', unsafe_allow_html=True)
    st.markdown('<div style="color:#7ec8e3;font-size:.75rem;letter-spacing:.15em;margin-bottom:8px">VOICE CORE ACTIVE</div>', unsafe_allow_html=True)

    # Voice input
    st.markdown('<div class="sec">🎙 Voice Input</div>', unsafe_allow_html=True)
    audio_val = st.audio_input("Speak to JARVIS", label_visibility="collapsed", key="voice_rec")

    if audio_val is not None:
        with st.spinner("Transcribing and processing, Sir..."):
            try:
                audio_bytes = audio_val.read() if hasattr(audio_val, "read") else audio_val.getvalue()
                files  = {"file": ("recording.wav", audio_bytes, "audio/wav")}
                resp   = requests.post(f"{SERVER}/voice", files=files,
                                       params={"user_id": "Dwijas"}, timeout=60)
                # Get answer from headers (server returns TTS audio)
                transcript = resp.headers.get("X-Transcript", "")
                answer     = resp.headers.get("X-Answer", "")

                if resp.status_code == 200 and transcript:
                    # Play TTS audio response
                    st.audio(io.BytesIO(resp.content), format="audio/mp3", autoplay=True)
                    ts = datetime.datetime.now().strftime("%H:%M:%S")
                    st.session_state.messages.append({"role":"you","text":f"🎙 {transcript}","ts":ts})
                    st.session_state.messages.append({"role":"jarvis","text":answer or "Response delivered.","ts":ts})
                    prune_and_archive_chat()
                else:
                    err = resp.json().get("error","Voice processing unavailable.") if resp.headers.get("content-type","").startswith("application/json") else "Voice processing unavailable."
                    st.warning(err)
            except Exception as e:
                st.warning(f"Voice error: {e}")
        run_gc()

    st.markdown('</div>', unsafe_allow_html=True)

    # Text chat
    st.markdown('<div class="glass">', unsafe_allow_html=True)
    st.markdown('<div class="sec">💬 Conversation</div>', unsafe_allow_html=True)

    chat_input = st.chat_input("Ask JARVIS anything, Sir...")
    if chat_input:
        ts     = datetime.datetime.now().strftime("%H:%M:%S")
        answer = cached_ask(chat_input)
        st.session_state.messages.append({"role":"you","text":chat_input,"ts":ts})
        st.session_state.messages.append({"role":"jarvis","text":answer,"ts":ts})
        prune_and_archive_chat()
        run_gc()

    # Display last MAX_CHAT_RAM messages newest-first
    for msg in reversed(st.session_state.messages[-MAX_CHAT_RAM:]):
        if msg["role"] == "you":
            st.markdown(f'<div class="you">▶ {msg["text"]}</div><div class="ts">{msg["ts"]}</div>',
                        unsafe_allow_html=True)
        else:
            st.markdown(f'<div class="jarv">◀ {msg["text"]}</div>',
                        unsafe_allow_html=True)

    archived_count = sum(1 for _ in open(CHAT_ARCHIVE, encoding="utf-8")) if os.path.exists(CHAT_ARCHIVE) else 0
    if archived_count:
        st.markdown(f'<div class="ts" style="text-align:center">+{archived_count} messages archived to disk</div>',
                    unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# RIGHT — Vision Feed + Teach
# ─────────────────────────────────────────────────────────────────────────────
with col_r:
    st.markdown('<div class="glass">', unsafe_allow_html=True)
    st.markdown('<div class="sec">👁 Vision / Contract Feed</div>', unsafe_allow_html=True)

    uploaded = st.file_uploader(
        "Upload contract or screenshot",
        type=["png", "jpg", "jpeg"],
        label_visibility="collapsed",
        key="vision_upload"
    )
    vision_prompt = st.text_input(
        "Custom analysis prompt (optional)",
        placeholder="Extract key dates and amounts...",
        key="vprompt"
    )

    if uploaded:
        st.image(uploaded, use_container_width=True)
        if st.button("⚡ Analyze with JARVIS Vision", use_container_width=True):
            with st.spinner("Engaging visual cortex, Sir..."):
                try:
                    img_bytes = uploaded.getvalue()
                    files  = {"file": (uploaded.name, img_bytes, uploaded.type)}
                    params = {"prompt": vision_prompt} if vision_prompt else {}
                    r      = requests.post(f"{SERVER}/vision", files=files, params=params, timeout=45)
                    result = r.json().get("analysis", "No analysis returned.")
                    st.session_state.last_vision = result
                except Exception as e:
                    st.session_state.last_vision = f"Vision error: {e}"
            run_gc()

    if st.session_state.last_vision:
        st.markdown(f'<div class="mbox" style="color:#c8f0ff;font-size:.82rem;line-height:1.5">'
                    f'{st.session_state.last_vision}</div>', unsafe_allow_html=True)

    st.markdown('</div>', unsafe_allow_html=True)

    # Knowledge injection panel
    st.markdown('<div class="glass">', unsafe_allow_html=True)
    st.markdown('<div class="sec">🧠 Teach JARVIS</div>', unsafe_allow_html=True)
    know_text = st.text_area("New knowledge to inject", placeholder="e.g. zHeight uses Procore for permits.", key="teach_txt", height=80)
    if st.button("💾 Commit to Memory", use_container_width=True):
        if know_text.strip():
            with st.spinner("Injecting and re-indexing, Sir..."):
                try:
                    r = requests.post(f"{SERVER}/teach",
                                      json={"user_id": "Dwijas", "knowledge": know_text.strip()}, timeout=10)
                    st.success(r.json().get("status", "Injected."))
                    fetch_status.clear()
                except Exception as e:
                    st.error(str(e))
            run_gc()
        else:
            st.warning("Nothing to commit, Sir.")
    st.markdown('</div>', unsafe_allow_html=True)

    # Manual GC button
    st.markdown('<div class="glass">', unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    with c1:
        if st.button("🗑 Clear Cache", use_container_width=True):
            st.cache_data.clear()
            run_gc()
            st.success("Cache cleared.")
    with c2:
        if st.button("🔄 Refresh", use_container_width=True):
            fetch_status.clear()
            get_metrics.clear()
            read_health_log.clear()
            st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)
