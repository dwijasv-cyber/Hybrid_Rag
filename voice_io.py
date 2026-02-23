"""
voice_io.py — JARVIS Voice I/O Module
STT: faster-whisper (offline, lightweight)
TTS: edge-tts with en-GB-RyanNeural (British JARVIS persona)
"""
import asyncio, os, tempfile, datetime
import edge_tts
from faster_whisper import WhisperModel

# Load Whisper once at import — use "base" for speed/accuracy balance
_whisper_model = None

def _get_whisper():
    global _whisper_model
    if _whisper_model is None:
        print("[VoiceIO]: Loading Whisper base model...")
        _whisper_model = WhisperModel("base", device="cpu", compute_type="int8")
        print("[VoiceIO]: Whisper ready.")
    return _whisper_model


def transcribe(audio_path: str) -> str:
    """Transcribe an audio file to text using faster-whisper."""
    try:
        model = _get_whisper()
        segments, info = model.transcribe(audio_path, beam_size=5)
        text = " ".join(seg.text.strip() for seg in segments)
        print(f"[VoiceIO]: Transcribed ({info.language}): {text}")
        return text.strip()
    except Exception as e:
        print(f"[VoiceIO]: Transcription error: {e}")
        return ""


async def speak_async(text: str, output_path: str = None) -> str:
    """Convert text to speech using Edge-TTS. Returns path to MP3 file."""
    if output_path is None:
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = os.path.join(tempfile.gettempdir(), f"jarvis_tts_{ts}.mp3")
    try:
        communicate = edge_tts.Communicate(text, voice="en-GB-RyanNeural")
        await communicate.save(output_path)
        print(f"[VoiceIO]: TTS saved to {output_path}")
        return output_path
    except Exception as e:
        print(f"[VoiceIO]: TTS error: {e}")
        return ""


def speak(text: str, output_path: str = None) -> str:
    """Synchronous wrapper for speak_async."""
    return asyncio.run(speak_async(text, output_path))


def play_audio(path: str):
    """Play audio file using Windows built-in player (no extra deps)."""
    try:
        import subprocess
        subprocess.Popen(["powershell", "-Command", f"(New-Object Media.SoundPlayer '{path}').PlaySync()"],
                         creationflags=subprocess.CREATE_NO_WINDOW)
    except Exception as e:
        print(f"[VoiceIO]: Playback error: {e}")


def speak_and_play(text: str):
    """Full pipeline: text → Edge-TTS MP3 → play."""
    path = speak(text)
    if path:
        play_audio(path)
