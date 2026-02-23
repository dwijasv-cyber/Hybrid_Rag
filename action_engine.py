"""
action_engine.py — JARVIS Windows Action Engine
Handles executive commands: play music, open apps, send WhatsApp, audit files.
Called from the LangGraph action_node in demo1.py.
"""
import os, time, subprocess, webbrowser
from urllib.parse import quote_plus

try:
    import pyautogui
    pyautogui.PAUSE = 0.5
    pyautogui.FAILSAFE = True
    _PYAUTOGUI_OK = True
except Exception:
    _PYAUTOGUI_OK = False

# ── App Paths ──────────────────────────────────────────────────────────────
APP_PATHS = {
    "figma":     r"C:\Users\admin\AppData\Local\Figma\Figma.exe",
    "vscode":    r"C:\Users\admin\AppData\Local\Programs\Microsoft VS Code\Code.exe",
    "whatsapp":  r"C:\Users\admin\AppData\Local\WhatsApp\WhatsApp.exe",
    "spotify":   r"C:\Users\admin\AppData\Roaming\Spotify\Spotify.exe",
    "notepad":   r"C:\Windows\System32\notepad.exe",
    "explorer":  r"C:\Windows\explorer.exe",
}

# ── Intent Detection ───────────────────────────────────────────────────────
def detect_action(text: str) -> str | None:
    """Returns action type or None if not an action command."""
    t = text.lower().strip()
    if t.startswith("play "):          return "play"
    if t.startswith("open "):          return "open"
    if "send whatsapp" in t:           return "whatsapp"
    if t.startswith("audit "):         return "audit"
    if "open youtube" in t:            return "play"
    return None


# ── Action Dispatchers ─────────────────────────────────────────────────────
def play_music(query: str) -> str:
    """Search YouTube for query and open in browser."""
    search_url = f"https://www.youtube.com/results?search_query={quote_plus(query)}"
    webbrowser.open(search_url)
    time.sleep(3)
    if _PYAUTOGUI_OK:
        # Click first video result (approximate position — works for 1080p)
        try:
            pyautogui.moveTo(640, 400, duration=0.5)
            pyautogui.click()
            return f"Playing '{query}' on YouTube, Sir."
        except Exception as e:
            return f"Opened YouTube search for '{query}'. Auto-click failed: {e}"
    return f"Opened YouTube search for '{query}', Sir."


def open_app(app_name: str) -> str:
    """Launch a known application by name."""
    key = app_name.lower().strip()
    path = APP_PATHS.get(key)
    if path and os.path.exists(path):
        subprocess.Popen([path])
        return f"{app_name.title()} is launching, Sir."
    # Fallback: try shell start
    try:
        os.startfile(key)
        return f"Attempting to open {app_name}, Sir."
    except Exception as e:
        return f"Could not open {app_name}: {e}"


def send_whatsapp(contact: str, message: str) -> str:
    """Open WhatsApp Desktop, find contact, and send message via pyautogui."""
    if not _PYAUTOGUI_OK:
        return "pyautogui unavailable — cannot automate WhatsApp."
    try:
        # Ensure WhatsApp is open
        wa_path = APP_PATHS.get("whatsapp", "")
        if wa_path and os.path.exists(wa_path):
            subprocess.Popen([wa_path])
            time.sleep(4)

        # Ctrl+F to focus search
        pyautogui.hotkey("ctrl", "f")
        time.sleep(1)
        pyautogui.typewrite(contact, interval=0.05)
        time.sleep(2)
        pyautogui.press("enter")
        time.sleep(1)
        # Click message box and type
        pyautogui.hotkey("ctrl", "f")  # dismiss search
        time.sleep(0.5)
        pyautogui.click(640, 900)       # approximate message input
        time.sleep(0.5)
        pyautogui.typewrite(message, interval=0.03)
        pyautogui.press("enter")
        return f"Message sent to {contact} on WhatsApp, Sir."
    except Exception as e:
        return f"WhatsApp automation failed: {e}"


def audit_file(filepath: str) -> str:
    """Open a file and return path for vision analysis (caller handles Gemini)."""
    if not os.path.exists(filepath):
        return f"File not found: {filepath}"
    try:
        os.startfile(filepath)
        return f"AUDIT_REQUESTED:{filepath}"   # Signal to demo1.py to call vision_module
    except Exception as e:
        return f"Could not open file: {e}"


def parse_and_execute(text: str) -> str | None:
    """
    Master dispatcher. Returns response string if action was taken, None if not an action.
    """
    t = text.strip()
    action = detect_action(t)
    if action is None:
        return None

    tl = t.lower()
    if action == "play":
        query = t[5:].strip() if tl.startswith("play ") else t
        return play_music(query)

    if action == "open":
        app = t[5:].strip()
        return open_app(app)

    if action == "whatsapp":
        # Pattern: "send whatsapp to [name]: [message]"
        try:
            after    = tl.split("send whatsapp to")[1]
            contact  = after.split(":")[0].strip().title()
            message  = after.split(":", 1)[1].strip() if ":" in after else "Hello"
            return send_whatsapp(contact, message)
        except Exception:
            return "Could not parse WhatsApp command. Format: 'send whatsapp to [name]: [message]'"

    if action == "audit":
        filepath = t[6:].strip()
        return audit_file(filepath)

    return None
