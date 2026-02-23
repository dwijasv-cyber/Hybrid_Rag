"""
file_observer.py — JARVIS Live Knowledge Observer
Monitors ./data/ for new/modified .txt and .md files.
Triggers a live ChromaDB re-index without server restart.
Launched as a daemon thread by demo1.py on startup.
"""
import time, os
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

_pipeline_ref = None   # set by demo1.py at startup


class KnowledgeHandler(FileSystemEventHandler):
    WATCH_EXTS = {".txt", ".md"}

    def _should_process(self, path: str) -> bool:
        return os.path.splitext(path)[1].lower() in self.WATCH_EXTS

    def on_created(self, event):
        if not event.is_directory and self._should_process(event.src_path):
            print(f"[Observer]: New knowledge file detected: {os.path.basename(event.src_path)}")
            self._trigger_reindex()

    def on_modified(self, event):
        if not event.is_directory and self._should_process(event.src_path):
            print(f"[Observer]: Knowledge file updated: {os.path.basename(event.src_path)}")
            self._trigger_reindex()

    def _trigger_reindex(self):
        if _pipeline_ref:
            import threading
            threading.Thread(target=_pipeline_ref.reindex, daemon=True).start()


def start_observer(pipeline, data_dir: str = "data") -> Observer:
    """Call this at FastAPI startup to begin watching ./data/ for changes."""
    global _pipeline_ref
    _pipeline_ref = pipeline

    os.makedirs(data_dir, exist_ok=True)
    handler  = KnowledgeHandler()
    observer = Observer()
    observer.schedule(handler, path=data_dir, recursive=False)
    observer.daemon = True
    observer.start()
    print(f"[Observer]: Watching '{data_dir}' for knowledge updates, Sir.")
    return observer
