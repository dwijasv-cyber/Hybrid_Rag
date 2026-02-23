"""
watchdog_jarvis.py — JARVIS Self-Healing Process Monitor
- Polls port 8000 every 30s (reduced from 10s to save CPU)
- Exponential backoff on repeated failures (prevents restart storm)
- Thermal cooldown: if >3 consecutive crashes detected, pauses 5 min
- Sets restarted server to IDLE priority to cap CPU
"""
import time, subprocess, datetime, os, sys
import psutil

VENV_PYTHON   = r"c:\Users\admin\OneDrive\Documents\GitHub\Hybrid_Rag\personal-phone-agent\venv\Scripts\python.exe"
SERVER_DIR    = r"c:\Users\admin\OneDrive\Documents\GitHub\Hybrid_Rag"
SERVER_CMD    = [VENV_PYTHON, "-m", "uvicorn", "demo1:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
HEALTH_LOG    = os.path.join(SERVER_DIR, "system_health.log")
POLL_INTERVAL = 30   # seconds — was 10, reduced to save CPU
MAX_BACKOFF   = 120  # max seconds between restart attempts

_server_proc   = None
_fail_count    = 0


def log(msg: str):
    ts   = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [WATCHDOG] {msg}"
    print(line)
    with open(HEALTH_LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def is_port_alive(port: int) -> bool:
    try:
        for conn in psutil.net_connections(kind="inet"):
            if conn.laddr.port == port and conn.status == "LISTEN":
                return True
    except Exception:
        pass
    return False


def kill_zombies(port: int):
    try:
        for conn in psutil.net_connections(kind="inet"):
            if conn.laddr.port == port and conn.pid:
                try:
                    psutil.Process(conn.pid).kill()
                    log(f"Cleared zombie PID {conn.pid} on port {port}.")
                except Exception:
                    pass
    except Exception:
        pass


def set_low_priority(pid: int):
    """Lower process priority to IDLE to reduce CPU competition."""
    try:
        p = psutil.Process(pid)
        p.nice(psutil.IDLE_PRIORITY_CLASS)   # Windows
    except AttributeError:
        try:
            p.nice(19)  # Unix lowest
        except Exception:
            pass
    except Exception:
        pass


def start_server() -> subprocess.Popen:
    global _server_proc, _fail_count
    kill_zombies(8000)
    time.sleep(2)
    _server_proc = subprocess.Popen(
        SERVER_CMD,
        cwd=SERVER_DIR,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
    )
    set_low_priority(_server_proc.pid)
    log(f"Mainframe restarted. PID={_server_proc.pid}.")
    log("Apologies, Sir. The mainframe encountered a minor hiccup but I have recalibrated the arrays.")
    _fail_count += 1
    return _server_proc


def main():
    global _server_proc, _fail_count
    log("JARVIS Watchdog online. Monitoring port 8000 every 30s.")

    # Set THIS process to low priority too
    try:
        psutil.Process(os.getpid()).nice(psutil.IDLE_PRIORITY_CLASS)
    except Exception:
        pass

    # Give server time to start on initial launch
    time.sleep(20)

    while True:
        try:
            alive = is_port_alive(8000)

            if not alive:
                # ── Thermal Cooldown: pause 5 min after 3+ consecutive crashes ──
                if _fail_count >= 3:
                    cooldown = 300  # 5 minutes
                    log(f"THERMAL COOLDOWN: {_fail_count} consecutive failures detected. "
                        f"Pausing {cooldown}s to prevent overload, Sir.")
                    time.sleep(cooldown)
                    _fail_count = 0   # fresh slate after cooldown
                    log("Cooldown complete. Resuming normal monitoring.")

                # Exponential backoff for the current restart attempt
                backoff = min(POLL_INTERVAL * (2 ** min(_fail_count, 3)), MAX_BACKOFF)
                log(f"Port 8000 is down. Restart #{_fail_count + 1} — backoff {backoff}s.")
                _server_proc = start_server()
                time.sleep(backoff)  # longer grace period on repeated failures

            else:
                _fail_count = 0  # reset on success
                # Check if our tracked process exited
                if _server_proc and _server_proc.poll() is not None:
                    log(f"Server process (PID {_server_proc.pid}) exited. Restarting.")
                    _server_proc = start_server()
                    time.sleep(25)

        except Exception as e:
            log(f"Watchdog error: {e}")

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
