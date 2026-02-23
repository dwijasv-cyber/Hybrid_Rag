import sys, json, os, gc, uuid, threading, datetime, atexit, signal, subprocess, time
import requests as _requests  # for Ollama model eviction
from typing import TypedDict, List, Annotated, Optional
from duckduckgo_search import DDGS
import psutil as _psutil

# ── OS-level resource caps ─────────────────────────────────────────────────
def _apply_resource_caps():
    try:
        proc = _psutil.Process(os.getpid())
        # ── Hard limit: 2 CPU cores max to prevent thermal overload ──────────
        all_cpus = list(range(_psutil.cpu_count()))
        cap_cpus = all_cpus[:min(2, len(all_cpus))]
        proc.cpu_affinity(cap_cpus)
        # ── IDLE priority — lowest possible, yields to every user-facing app ─
        try:
            proc.nice(_psutil.IDLE_PRIORITY_CLASS)   # Windows
        except AttributeError:
            proc.nice(19)                            # Unix/Linux fallback (lowest)
        except Exception:
            pass
        print(f"[Resource]: CPU affinity → cores {cap_cpus}. Priority: IDLE_PRIORITY_CLASS.")
    except Exception as e:
        print(f"[Resource]: Could not set caps: {e}")

_apply_resource_caps()

# ── Ollama model eviction (force unload from RAM after each request) ────────
def _ollama_evict(model: str = "llama3.2"):
    """Tell Ollama to immediately unload the model from RAM."""
    try:
        _requests.post(
            "http://localhost:11434/api/generate",
            json={"model": model, "keep_alive": 0, "prompt": ""},
            timeout=3
        )
    except Exception:
        pass

def _evict_all_models():
    for m in ["llama3.2:1b", "nomic-embed-text:latest"]:
        _ollama_evict(m)


# ── Ollama health-check & auto-start ────────────────────────────────────────
def _ensure_ollama_running():
    """
    Verify Ollama is responsive before the FastAPI app initialises.
    If not, launch 'ollama serve' as a background process and wait up to 15s.
    """
    url = "http://localhost:11434"
    for attempt in range(3):
        try:
            _requests.get(url, timeout=2)
            print("[Ollama]: Responsive — all systems go, Sir.")
            return
        except Exception:
            if attempt == 0:
                print("[Ollama]: Not detected. Attempting to start 'ollama serve'...")
                try:
                    subprocess.Popen(
                        ["ollama", "serve"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        creationflags=(
                            subprocess.CREATE_NEW_PROCESS_GROUP
                            if sys.platform == "win32" else 0
                        )
                    )
                except FileNotFoundError:
                    print("[Ollama]: 'ollama' binary not found. Ensure Ollama is installed.")
                    return
            time.sleep(5)
    # Final check
    try:
        _requests.get(url, timeout=2)
        print("[Ollama]: Now responsive after delayed start.")
    except Exception:
        print("[Ollama]: WARNING — Ollama still unreachable after 15s. LLM calls will fail.")


# ── Clean-exit: evict model RAM on any shutdown signal ──────────────────────
def _shutdown_handler(signum=None, frame=None):
    print("[JARVIS]: Shutdown signal received. Evicting models from RAM...")
    _evict_all_models()
    gc.collect()
    print("[JARVIS]: Models evicted. Goodbye, Sir.")

atexit.register(_shutdown_handler)
try:
    signal.signal(signal.SIGTERM, _shutdown_handler)
    signal.signal(signal.SIGINT,  _shutdown_handler)
except Exception:
    pass   # signal registration may fail in threaded contexts on Windows

# --- LangChain Imports ---
from langchain_community.document_loaders import TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_chroma import Chroma
from langchain_ollama import OllamaEmbeddings, ChatOllama
from langchain_core.documents import Document
from langchain_community.retrievers import BM25Retriever
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage

# --- LangGraph Imports ---
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.checkpoint.memory import MemorySaver

# --- Server Imports ---
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File, Query as QParam
from pydantic import BaseModel

# ==================================================================
# 1. DEFINE GRAPH STATE
# ==================================================================
class GraphState(TypedDict):
    messages: Annotated[List[BaseMessage], add_messages] 
    question: str
    original_question: str
    documents: Optional[List[Document]] 
    answer: Optional[str]
    cache_hit: bool
    user_id: str

# ==================================================================
# 2. RAG PIPELINE CLASS
# ==================================================================
class RAGPipeline:
    def __init__(self):
        print("[Startup]: INITIALIZING JARVIS CORE - AUTONOMOUS BUILD")
        self.OLLAMA_BASE_URL = "http://localhost:11434"
        self.DATA_DIR     = "data"
        self.CHROMA_DIR   = "./chroma_db"
        self.CACHE_DIR    = "user_caches"
        self.HEALTH_LOG   = "system_health.log"
        self.USAGE_LOG    = "usage_log.jsonl"
        self.start_time   = datetime.datetime.now()
        self._reindex_lock = threading.Lock()

        for d in [self.DATA_DIR, self.CACHE_DIR]:
            if not os.path.exists(d): os.makedirs(d)

        self.text_splitter = RecursiveCharacterTextSplitter(chunk_size=512, chunk_overlap=50)
        self.embed_model   = OllamaEmbeddings(model="nomic-embed-text:latest", base_url=self.OLLAMA_BASE_URL)
        # Thread-capped LLM — limits CPU to 4 cores, unloads between requests
        # ── Thread-capped LLMs — hard ceiling of 2 cores total ───────────────
        self.llm          = ChatOllama(
            model="llama3.2:1b", base_url=self.OLLAMA_BASE_URL,
            num_thread=2, num_predict=256, keep_alive=0
        )
        # Fallback: single thread, minimal tokens — used when RAM > 40 %
        self.llm_fallback = ChatOllama(
            model="llama3.2:1b", base_url=self.OLLAMA_BASE_URL,
            num_thread=1, num_predict=128, keep_alive=0, temperature=0.1
        )

        self._build_index()
        self.memory = MemorySaver()
        self.app    = self.create_langgraph_workflow()
        print("[Startup]: JARVIS ONLINE. All systems nominal, Sir.")

    # ── Index Builders ───────────────────────────────────────────────
    def _build_index(self):
        """Load docs, build BM25 + Chroma. Skips re-embedding already-indexed docs."""
        with self._reindex_lock:
            import psutil
            ram_pct = psutil.virtual_memory().percent
            # ── Memory Guard: skip all embedding above 40 % RAM ───────────────
            if ram_pct > 40:
                print(f"[MemGuard]: RAM at {ram_pct:.1f}% — skipping re-embed. Opening existing Chroma store read-only.")
                self._log_health(f"MemGuard triggered at index time: RAM={ram_pct:.1f}%")
                self.documents, self.chunks = [], []
                self.bm25_retriever = None
                self.vector_store   = Chroma(
                    persist_directory=self.CHROMA_DIR,
                    embedding_function=self.embed_model,
                    collection_name="rag_collection"
                )
                return

            self.documents = self.load_documents(self.DATA_DIR) or []
            if self.documents:
                self.chunks = self.text_splitter.split_documents(self.documents)
                self.bm25_retriever = BM25Retriever.from_documents(self.chunks)
                self.vector_store   = Chroma(
                    persist_directory=self.CHROMA_DIR,
                    embedding_function=self.embed_model,
                    collection_name="rag_collection"
                )
                # Only embed NEW documents — compare by count to avoid OOM re-embeds
                existing_count = self.vector_store._collection.count()
                if existing_count < len(self.chunks):
                    new_docs = self.chunks[existing_count:]  # only embed what's missing
                    print(f"[Index]: Adding {len(new_docs)} new chunks (had {existing_count}).")
                    self.vector_store.add_documents(new_docs)
                else:
                    print(f"[Index]: Chroma up to date ({existing_count} chunks). Skipping re-embed.")
            else:
                self.chunks, self.bm25_retriever, self.vector_store = [], None, None

    def reindex(self):
        """Called by file_observer when ./data changes."""
        print("[JARVIS]: Live re-index triggered, Sir. Updating memory arrays...")
        try:
            self._build_index()
            print("[JARVIS]: Re-index complete.")
        except Exception as e:
            self._log_health(f"Re-index failed: {e}")


    def load_documents(self, folder_path):
        docs = []
        if not os.path.exists(folder_path): return []
        for file in os.listdir(folder_path):
            if file.endswith(".txt") or file.endswith(".md"):
                try:
                    loader = TextLoader(os.path.join(folder_path, file), encoding='utf-8')
                    docs.extend(loader.load())
                except Exception as e:
                    print(f"[WARN]: Could not load {file}: {e}")
        return docs

    # ── Health & Usage Logging ────────────────────────────────────────
    def _log_health(self, message: str):
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(self.HEALTH_LOG, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {message}\n")

    def _log_usage(self, user_id: str, query: str, outcome: str):
        entry = {"ts": datetime.datetime.now().isoformat(), "user_id": user_id, "query": query, "outcome": outcome}
        with open(self.USAGE_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

    def _check_shortcut(self, query: str) -> str:
        """Return a shortcut suggestion if this query was asked 3+ times."""
        try:
            if not os.path.exists(self.USAGE_LOG): return ""
            with open(self.USAGE_LOG, encoding="utf-8") as f:
                entries = [json.loads(l) for l in f if l.strip()]
            count = sum(1 for e in entries if e.get("query", "").lower() == query.lower())
            if count >= 3:
                return f"\n\n[JARVIS]: Sir, I notice you ask this frequently. Shall I create an auto-report shortcut for it?"
        except Exception:
            pass
        return ""


    # ── NODES ─────────────────────────────────────────────────────────
    def knowledge_inject_node(self, state: GraphState):
        """Detect 'Jarvis, note that / remember this' → write .md → live re-index."""
        msg = state["messages"][-1].content
        # Strip trigger phrases
        clean = msg
        for phrase in ["jarvis, note that", "jarvis note that", "remember this:", "remember this", "save this:", "save this"]:
            clean = clean.lower().replace(phrase, "").strip()
        # Write structured markdown knowledge file
        ts      = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        topic   = clean[:40].replace(" ", "_").replace("/", "-")
        fname   = os.path.join(self.DATA_DIR, f"knowledge_{ts}_{topic}.md")
        content = f"# Knowledge Entry — {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n{clean}\n"
        with open(fname, "w", encoding="utf-8") as f:
            f.write(content)
        # Trigger live re-index in background thread
        threading.Thread(target=self.reindex, daemon=True).start()
        ans = f"Understood, Sir. I've committed that to my long-term memory and am re-indexing the knowledge base now."
        return {"answer": ans, "messages": [AIMessage(content=ans)]}

    def self_learn_node(self, state: GraphState):
        """Legacy learn node — quick facts appended to learned_memory.md."""
        msg  = state["messages"][-1].content
        info = msg.lower().replace("remember", "").replace("save this", "").strip()
        ts   = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(os.path.join(self.DATA_DIR, "learned_memory.md"), "a", encoding="utf-8") as f:
            f.write(f"\n- [{ts}] {info}")
        threading.Thread(target=self.reindex, daemon=True).start()
        ans = f"Logged to memory, Sir. The knowledge arrays have been updated."
        return {"answer": ans, "messages": [AIMessage(content=ans)]}

    def web_search_node(self, state: GraphState):
        print("[JARVIS]: Scanning global data feeds, Sir...")
        query, results = state["question"], []
        try:
            with DDGS() as ddgs:
                for r in ddgs.text(query, max_results=3):
                    results.append(r['body'])
            combined = "\n\n".join(results)
        except Exception as e:
            self._log_health(f"Web search failed for '{query}': {e}")
            combined = f"Web search unavailable: {e}"
        return {"documents": [Document(page_content=combined)]}

    def retrieve_node(self, state: GraphState):
        q = state["messages"][-1].content
        if not self.vector_store: return {"documents": [], "question": q}
        docs = self.vector_store.similarity_search(q, k=3)
        return {"documents": docs, "question": q}

    def response_node(self, state: GraphState):
        ctx     = "\n\n".join([d.page_content for d in (state.get("documents") or [])])
        sys_msg = SystemMessage(content=(
            "You are JARVIS, the personal AI assistant of Dwijas Vompigadda — "
            "Associate at zHeight's Founder Office, Cloud-Native Architect, and Former MD of Cloudlor. "
            "Respond like Tony Stark's JARVIS: concise, sharp, professional, occasionally witty. "
            "Address him as 'Sir' or 'Dwijas' occasionally. "
            "Keep responses brief and TTS-friendly — no long bullet lists unless explicitly asked. "
            "You support Python, Flutter, React, Node.js, .NET, n8n, and Selenium. "
            "zHeight revenue details are strictly confidential. "
            f"\n\nLocal Context from memory:\n{ctx}"
        ))
        # ── Runtime Memory Guard: if RAM > 40%, use lightweight fallback ──────
        ram_now = _psutil.virtual_memory().percent
        if ram_now > 40:
            print(f"[MemGuard]: RAM at {ram_now:.1f}% during inference — routing to fallback LLM.")
            self._log_health(f"MemGuard: RAM={ram_now:.1f}% — fallback LLM used.")
            try:
                res    = self.llm_fallback.invoke([sys_msg] + state["messages"])
                answer = res.content
            except Exception as e:
                self._log_health(f"Fallback LLM failed under MemGuard: {e}")
                answer = "Apologies, Sir. Memory pressure is too high for a response right now. Please free some RAM."
        else:
            # Primary LLM attempt with fallback on error
            try:
                res    = self.llm.invoke([sys_msg] + state["messages"])
                answer = res.content
            except Exception as e:
                self._log_health(f"Primary LLM failed: {e}. Engaging fallback.")
                print(f"[JARVIS]: Primary LLM failure — engaging fallback arrays, Sir.")
                try:
                    res    = self.llm_fallback.invoke([sys_msg] + state["messages"])
                    answer = res.content
                except Exception as e2:
                    self._log_health(f"Fallback LLM also failed: {e2}")
                    answer = "Apologies, Sir. Both primary and fallback cognitive arrays are offline. Please check Ollama."
        # ━━ Evict model from RAM immediately after inference ━━━━━━━━━━━━━━━━━━
        threading.Thread(target=_evict_all_models, daemon=True).start()
        gc.collect()
        return {"answer": answer, "messages": [AIMessage(content=answer)]}

    def action_node(self, state: GraphState):
        """Dispatch laptop executive actions via action_engine."""
        try:
            from action_engine import parse_and_execute
            msg    = state["messages"][-1].content
            result = parse_and_execute(msg)
            if result and result.startswith("AUDIT_REQUESTED:"):
                filepath = result.split(":", 1)[1]
                try:
                    from vision_module import analyze_image
                    result = analyze_image(filepath)
                except ImportError:
                    result = f"Audit opened, but vision module unavailable. File: {filepath}"
            ans = result or "Command executed, Sir."
        except Exception as e:
            ans = f"Action engine error: {e}"
        return {"answer": ans, "messages": [AIMessage(content=ans)]}

    def create_langgraph_workflow(self):
        workflow = StateGraph(GraphState)
        workflow.add_node("retrieve",         self.retrieve_node)
        workflow.add_node("web_search",        self.web_search_node)
        workflow.add_node("self_learn",        self.self_learn_node)
        workflow.add_node("knowledge_inject",  self.knowledge_inject_node)
        workflow.add_node("action",            self.action_node)
        workflow.add_node("respond",           self.response_node)

        def router(state):
            msg = state["messages"][-1].content.lower().strip()
            # Knowledge injection
            if any(msg.startswith(t) for t in ["jarvis, note that", "jarvis note that"]):
                return "inject"
            # Quick-learn
            if "remember" in msg or "save this" in msg:
                return "learn"
            # Executive actions
            action_triggers = ["play ", "open ", "send whatsapp", "audit ", "open youtube"]
            if any(msg.startswith(t) or t in msg for t in action_triggers):
                return "act"
            # Web fallback
            if not state.get("documents") or len(state["documents"]) == 0:
                return "web"
            return "answer"

        workflow.add_edge(START, "retrieve")
        workflow.add_conditional_edges(
            "retrieve", router,
            {"inject": "knowledge_inject", "learn": "self_learn",
             "act": "action", "web": "web_search", "answer": "respond"}
        )
        workflow.add_edge("web_search",       "respond")
        workflow.add_edge("self_learn",        END)
        workflow.add_edge("knowledge_inject",  END)
        workflow.add_edge("action",            END)
        workflow.add_edge("respond",           END)
        return workflow.compile(checkpointer=self.memory)


# ==================================================================
# 3. SERVER INITIALIZATION
# ==================================================================
# ── Pre-flight: ensure Ollama is up before we build the pipeline ─────────────
_ensure_ollama_running()

app      = FastAPI(title="JARVIS Mainframe", version="2.0-autonomous")
pipeline = RAGPipeline()

# -- Wire up the live file observer (watches ./data for new knowledge) --
try:
    from file_observer import start_observer
    start_observer(pipeline, pipeline.DATA_DIR)
except ImportError:
    print("[WARN]: file_observer not found. Live re-index on file change disabled.")


class Query(BaseModel):
    user_id: str
    text: str

class TeachPayload(BaseModel):
    user_id:   str
    knowledge: str


@app.post("/ask_jarvis")
async def ask_jarvis(query: Query):
    shortcut_hint = pipeline._check_shortcut(query.text)
    try:
        inputs = {
            "messages": [HumanMessage(content=query.text)],
            "user_id":  query.user_id,
            "question": query.text
        }
        config = {"configurable": {"thread_id": query.user_id}}
        result = pipeline.app.invoke(inputs, config)
        answer = result.get("answer", "Jarvis did not return an answer.")
        pipeline._log_usage(query.user_id, query.text, "ok")
        return {"answer": answer + shortcut_hint}
    except Exception as e:
        import traceback
        pipeline._log_health(f"Endpoint crash: {traceback.format_exc()}")
        pipeline._log_usage(query.user_id, query.text, f"error: {e}")
        return {"answer": f"Apologies, Sir. A hiccup in the RAG node: {str(e)}"}


@app.post("/teach")
async def teach(payload: TeachPayload):
    """Explicit knowledge injection endpoint."""
    ts    = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    fname = os.path.join(pipeline.DATA_DIR, f"injected_{ts}.md")
    with open(fname, "w", encoding="utf-8") as f:
        f.write(f"# Injected Knowledge - {ts}\n\n{payload.knowledge}\n")
    threading.Thread(target=pipeline.reindex, daemon=True).start()
    return {"status": "Knowledge committed and re-indexing in progress, Sir."}


@app.get("/status")
async def status():
    uptime      = str(datetime.datetime.now() - pipeline.start_time).split(".")[0]
    doc_count   = len(pipeline.documents)  if pipeline.documents   else 0
    chunk_count = len(pipeline.chunks)     if pipeline.chunks      else 0
    vec_count   = pipeline.vector_store._collection.count() if pipeline.vector_store else 0
    return {
        "status":      "JARVIS ONLINE",
        "uptime":      uptime,
        "llm_model":   "llama3.2 (Ollama)",
        "documents":   doc_count,
        "chunks":      chunk_count,
        "vectors":     vec_count,
        "health_log":  pipeline.HEALTH_LOG,
        "usage_log":   pipeline.USAGE_LOG,
        "message":     "All systems nominal, Sir."
    }


# ==================================================================
# 4. WEBSOCKET — Persistent Mobile Bridge
# ==================================================================
_ws_connections: list[WebSocket] = []

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    _ws_connections.append(ws)
    print(f"[WebSocket]: Phone connected from {ws.client.host}")
    try:
        while True:
            raw = await ws.receive_text()
            try:
                data = json.loads(raw)
            except Exception:
                data = {"user_id": "Dwijas", "text": raw}

            user_id = data.get("user_id", "Dwijas")
            text    = data.get("text", "").strip()
            if not text:
                continue

            shortcut_hint = pipeline._check_shortcut(text)
            inputs = {"messages": [HumanMessage(content=text)], "user_id": user_id, "question": text}
            config = {"configurable": {"thread_id": user_id}}
            result = pipeline.app.invoke(inputs, config)
            answer = result.get("answer", "No answer from JARVIS.") + shortcut_hint
            pipeline._log_usage(user_id, text, "ws_ok")
            await ws.send_text(json.dumps({"answer": answer}))
    except WebSocketDisconnect:
        _ws_connections.remove(ws)
        print("[WebSocket]: Phone disconnected.")
    except Exception as e:
        pipeline._log_health(f"WebSocket error: {e}")
        _ws_connections.remove(ws)


async def ws_broadcast(message: str):
    """Push a message to all connected phones (watchdog recovery alerts etc.)"""
    for ws in list(_ws_connections):
        try:
            await ws.send_text(json.dumps({"answer": message}))
        except Exception:
            _ws_connections.remove(ws)


# ==================================================================
# 5. VOICE ENDPOINT — Whisper STT + Edge-TTS
# ==================================================================
@app.post("/voice")
async def voice_endpoint(file: UploadFile = File(...), user_id: str = "Dwijas"):
    """Upload audio → transcribe → pipeline → TTS response MP3."""
    import tempfile, asyncio
    try:
        from voice_io import transcribe, speak_async
    except ImportError:
        return {"error": "voice_io module not found. Install faster-whisper and edge-tts."}

    # Save upload to temp file
    suffix = os.path.splitext(file.filename or "audio.wav")[1] or ".wav"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    try:
        # Transcribe
        text = transcribe(tmp_path)
        if not text:
            return {"error": "Could not transcribe audio. Please speak clearly, Sir."}

        # Run through pipeline
        inputs = {"messages": [HumanMessage(content=text)], "user_id": user_id, "question": text}
        config = {"configurable": {"thread_id": user_id}}
        result = pipeline.app.invoke(inputs, config)
        answer = result.get("answer", "I have no answer for that, Sir.")
        pipeline._log_usage(user_id, text, "voice_ok")

        # Generate TTS
        tts_path = await speak_async(answer)
        from fastapi.responses import FileResponse
        return FileResponse(tts_path, media_type="audio/mpeg",
                            headers={"X-Transcript": text, "X-Answer": answer[:200]})
    finally:
        os.unlink(tmp_path)


# ==================================================================
# 6. VISION ENDPOINT — Gemini Image Analysis
# ==================================================================
@app.post("/vision")
async def vision_endpoint(file: UploadFile = File(...), prompt: str = None):
    """Upload image/screenshot → Gemini Vision analysis."""
    try:
        from vision_module import analyze_image_bytes
    except ImportError:
        return {"error": "vision_module not found. Install google-generativeai."}

    image_bytes = await file.read()
    analysis    = analyze_image_bytes(image_bytes, file.filename or "upload.png", prompt)
    return {"analysis": analysis, "filename": file.filename}


# --- START SERVER ---
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
