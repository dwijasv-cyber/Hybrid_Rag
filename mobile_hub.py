"""
mobile_hub.py — JARVIS Mobile HUD (Moto G05 / Termux)
Run on phone: python mobile_hub.py

Features:
- Persistent WebSocket connection to JARVIS mainframe
- Earphone long-press trigger for STT via termux-api
- Termux-API bridge: calls, SMS, battery status
- Formatted terminal HUD output
"""
import asyncio, json, os, subprocess, sys, time, threading
import websockets

# ── CONFIG ──────────────────────────────────────────────────────────────────
SERVER_IP  = "10.163.48.16"       # Your PC's LAN IP
WS_URL     = f"ws://{SERVER_IP}:8000/ws"
USER_ID    = "Dwijas"
CHIME_FILE = "/data/data/com.termux/files/home/chime.mp3"  # optional

# ── Termux-API Helpers ──────────────────────────────────────────────────────
def termux_speak(text: str):
    """Use termux-tts-speak for quick local TTS."""
    subprocess.run(["termux-tts-speak", text], capture_output=True)

def termux_battery():
    result = subprocess.run(["termux-battery-status"], capture_output=True, text=True)
    try:
        data = json.loads(result.stdout)
        return f"Battery: {data.get('percentage', '?')}% | Status: {data.get('status', '?')}"
    except Exception:
        return "Battery: unavailable"

def termux_sms(number: str, message: str):
    subprocess.run(["termux-sms-send", "-n", number, message], capture_output=True)
    return f"SMS sent to {number}"

def termux_call(number: str):
    subprocess.run(["termux-telephony-call", number], capture_output=True)
    return f"Calling {number}..."

def stt_listen() -> str:
    """Use termux-speech-to-text to listen for a voice command."""
    print("\n🎙  [JARVIS]: Listening, Sir...")
    result = subprocess.run(
        ["termux-speech-to-text"],
        capture_output=True, text=True, timeout=15
    )
    text = result.stdout.strip()
    print(f"   You said: {text}")
    return text

# ── HUD Display ─────────────────────────────────────────────────────────────
def print_hud(message: str, tag: str = "JARVIS"):
    bar = "─" * 50
    print(f"\n╔{bar}╗")
    print(f"║  [{tag}]")
    for line in message.split("\n"):
        print(f"║  {line}")
    print(f"╚{bar}╝\n")

# ── Earphone Trigger ─────────────────────────────────────────────────────────
def earphone_listener(trigger_callback):
    """
    Background thread that watches termux-media-button for long-press.
    Calls trigger_callback() when detected.
    """
    print("[HUD]: Earphone trigger listener active.")
    while True:
        try:
            result = subprocess.run(
                ["termux-media-button"],
                capture_output=True, text=True, timeout=30
            )
            event = result.stdout.strip().lower()
            if "long_press" in event or "held" in event:
                print("[HUD]: Earphone long-press detected — activating STT")
                trigger_callback()
        except subprocess.TimeoutExpired:
            pass
        except Exception as e:
            print(f"[HUD]: Earphone listener error: {e}")
            time.sleep(5)

# ── WebSocket Client ─────────────────────────────────────────────────────────
async def ws_send_receive(ws, query: str) -> str:
    payload = json.dumps({"user_id": USER_ID, "text": query})
    await ws.send(payload)
    response = await asyncio.wait_for(ws.recv(), timeout=60)
    data = json.loads(response)
    return data.get("answer", "No response from mainframe.")

async def main_loop():
    print_hud("JARVIS Mobile HUD Online\nConnecting to mainframe...", "SYSTEM")
    reconnect_delay = 3

    while True:
        try:
            async with websockets.connect(WS_URL, ping_interval=20, ping_timeout=10) as ws:
                print_hud(f"Connected to {WS_URL}", "SYSTEM")
                reconnect_delay = 3

                # Earphone trigger in background thread
                def trigger():
                    query = stt_listen()
                    if query:
                        asyncio.run_coroutine_threadsafe(
                            ws_send_receive_and_display(ws, query),
                            asyncio.get_event_loop()
                        )

                ear_thread = threading.Thread(target=earphone_listener, args=(trigger,), daemon=True)
                ear_thread.start()

                # Manual text input loop
                while True:
                    query = await asyncio.get_event_loop().run_in_executor(
                        None, lambda: input("You: ").strip()
                    )
                    if not query:
                        continue
                    if query.lower() == "exit":
                        return
                    if query.lower() == "battery":
                        print_hud(termux_battery(), "SYSTEM")
                        continue

                    answer = await ws_send_receive(ws, query)
                    print_hud(answer, "JARVIS")
                    termux_speak(answer[:200])  # Speak first 200 chars locally

        except (websockets.ConnectionClosed, ConnectionRefusedError, OSError) as e:
            print(f"\n[HUD]: Connection lost ({e}). Retrying in {reconnect_delay}s...")
            await asyncio.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 2, 30)
        except Exception as e:
            print(f"[HUD]: Unexpected error: {e}")
            await asyncio.sleep(5)


async def ws_send_receive_and_display(ws, query: str):
    try:
        answer = await ws_send_receive(ws, query)
        print_hud(answer, "JARVIS")
        termux_speak(answer[:200])
    except Exception as e:
        print(f"[HUD]: Error: {e}")


if __name__ == "__main__":
    asyncio.run(main_loop())
