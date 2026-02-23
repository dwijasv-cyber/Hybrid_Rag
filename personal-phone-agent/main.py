from fastapi import FastAPI, Form
from twilio.twiml.voice_response import VoiceResponse
import ollama
import sys
import os
from datetime import datetime

# Path setup for Hybrid_Rag
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from demo1 import RAGPipeline 

app = FastAPI()
rag = RAGPipeline() 

def generate_status_report(number, name, reason, duration, language):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    report = (
        f"--- CALL STATUS REPORT ---\n"
        f"Time: {timestamp} | Language: {language}\n"
        f"Number: {number} | Name: {name}\n"
        f"Reason: {reason} | Duration: {duration}s\n"
        f"---------------------------\n\n"
    )
    # Using utf-8 to ensure Telugu and Hindi characters save correctly
    with open("chitti_logs.txt", "a", encoding="utf-8") as f:
        f.write(report)

@app.post("/voice")
async def handle_call(From: str = Form(...)):
    app.state.call_start = datetime.now()
    vr = VoiceResponse()
    # Multilingual greeting to detect the caller's language
    vr.say("Hi! I'm Chitti, Dwijas's assistant. Meeru evaru? Aap kaun bol rahe hain?", 
           voice='Polly.Chitra-Neural')
    vr.gather(input='speech', action='/respond', timeout=5)
    return str(vr)

@app.post("/respond")
async def handle_respond(SpeechResult: str = Form(...), From: str = Form(...)):
    # 1. LANGUAGE & DIALECT ANALYSIS
    analysis = ollama.chat(model='llama3.2', messages=[
        {'role': 'system', 'content': """
            Analyze the caller's speech:
            - Identify Language: English, Telugu, Hindi, or Tamil.
            - Extract: Name and Reason.
            - Filter: If it's a bot/telemarketer, category is 'SPAM'.
            Reply ONLY as: Category | Language | Name | Reason
        """},
        {'role': 'user', 'content': SpeechResult}
    ])
    
    parts = analysis['message']['content'].split('|')
    category = parts[0].strip() if len(parts) > 0 else "HUMAN"
    lang = parts[1].strip() if len(parts) > 1 else "English"
    name = parts[2].strip() if len(parts) > 2 else "Unknown"
    reason = parts[3].strip() if len(parts) > 3 else SpeechResult

    if "SPAM" in category.upper():
        vr = VoiceResponse()
        vr.hangup()
        return str(vr)

    # 2. DIALECT-SPECIFIC PERSONA (Andhra Telugu & Delhi Hindi)
    response = ollama.chat(model='llama3.2', messages=[
        {'role': 'system', 'content': f"""
            You are Chitti, Dwijas's human assistant. 
            Respond ONLY in {lang}. 
            
            DIALECT SPECIALIZATION:
            - HINDI: Use a Delhi-NCR 'Hinglish' style. Be professional, direct, and urban. 
              Use phrases like 'Dwijas abhi thoda busy hain,' or 'Main unhe inform kar deti hoon.'
            - TELUGU: Use pure Andhra Pradesh (Coastal/Andhra) style. 
              Use respectful suffixes like 'Andi' and 'Cheppandi.'
            
            WORKFLOW:
            - Ask for their name and relation to Dwijas.
            - Politely explain he is very busy with high-priority work and will call back.
            - NEVER say you are an AI. Use natural fillers like 'Hmm' or 'Theek hai.'
        """},
        {'role': 'user', 'content': SpeechResult}
    ])
    
    reply_text = response['message']['content']
    duration = (datetime.now() - app.state.call_start).seconds
    generate_status_report(From, name, reason, duration, lang)

    vr = VoiceResponse()
    # Chitra handles Hindi/Telugu beautifully; Joanna for English/Tamil
    voice_choice = 'Polly.Chitra-Neural' if lang in ['Hindi', 'Telugu'] else 'Polly.Joanna-Neural'
    
    vr.say(reply_text, voice=voice_choice)
    
    # End call if a callback is promised
    if any(word in reply_text.lower() for word in ["callback", "thirumbi", "call back", "cheshtharu", "baat karlenge"]):
        vr.hangup()
    else:
        vr.gather(input='speech', action='/respond', timeout=5)
        
    return str(vr)