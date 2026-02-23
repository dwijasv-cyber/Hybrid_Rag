"""
vision_module.py — JARVIS Vision Module
Analyzes images/contract screenshots via Gemini Vision.
Gracefully degrades if API quota is exhausted.
"""
import os, base64
import google.generativeai as genai
from PIL import Image

GOOGLE_API_KEY = "AIzaSyCcZ3N4gpmRinTzHnMVqI6Q9w9NniUIMpY"
VISION_MODEL   = "gemini-1.5-flash"

_client = None

def _get_client():
    global _client
    if _client is None:
        genai.configure(api_key=GOOGLE_API_KEY)
        _client = genai.GenerativeModel(VISION_MODEL)
    return _client


def analyze_image(image_path: str, prompt: str = None) -> str:
    """
    Analyze an image file with Gemini Vision.
    Default prompt focuses on contract/permit document analysis.
    """
    if not os.path.exists(image_path):
        return f"Image not found: {image_path}"

    if prompt is None:
        prompt = (
            "You are JARVIS, Dwijas's AI assistant. Analyze this document or image. "
            "If it's a contract or permit, extract: parties, key dates, dollar amounts, "
            "and any IBHS fire safety compliance items. "
            "Be concise and TTS-friendly. Address findings as 'Sir'."
        )
    try:
        client = _get_client()
        img    = Image.open(image_path)
        result = client.generate_content([prompt, img])
        return result.text
    except Exception as e:
        err = str(e)
        if "429" in err or "RESOURCE_EXHAUSTED" in err:
            return "Vision module temporarily offline, Sir. Gemini API quota exhausted — will auto-recover."
        if "NOT_FOUND" in err:
            return "Vision model unavailable. Please verify the Gemini API key."
        return f"Vision analysis error: {err}"


def analyze_image_bytes(image_bytes: bytes, filename: str = "upload.png", prompt: str = None) -> str:
    """Analyze raw image bytes — used by the FastAPI /vision endpoint."""
    tmp_path = os.path.join(os.path.dirname(__file__), f"_tmp_vision_{filename}")
    try:
        with open(tmp_path, "wb") as f:
            f.write(image_bytes)
        return analyze_image(tmp_path, prompt)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
