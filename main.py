import os
import json
import sqlite3
from dotenv import load_dotenv
from flask import Flask, request, render_template
import requests
from openai import OpenAI
from sqlalchemy import create_engine, Column, String, Text
from sqlalchemy.orm import declarative_base, sessionmaker

load_dotenv()

GROUPME_BOT_ID = os.getenv("GROUPME_BOT_ID")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")

client = OpenAI(api_key=OPENAI_API_KEY)

app = Flask(__name__)

Base = declarative_base()
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)

class Conversation(Base):
    __tablename__ = 'conversations'
    user_id = Column(String, primary_key=True)
    history = Column(Text)
    summary = Column(Text)

def init_db():
    Base.metadata.create_all(bind=engine)

init_db()

def get_user_convo(user_id):
    session = SessionLocal()
    convo = session.query(Conversation).filter_by(user_id=user_id).first()
    session.close()
    if convo:
        history = json.loads(convo.history)
        return history, convo.summary
    return [], ""

def save_user_convo(user_id, history, summary):
    session = SessionLocal()
    convo = session.query(Conversation).filter_by(user_id=user_id).first()
    MAX_HISTORY = 20

    if len(history) > MAX_HISTORY:
        new_summary = summarize_history(history)
        summary = (summary or "") + "\n\n" + new_summary
        history = [msg for msg in history if msg["role"] == "system"]

    if convo:
        convo.history = json.dumps(history)
        convo.summary = summary
    else:
        convo = Conversation(
            user_id=user_id,
            history=json.dumps(history),
            summary=summary
        )
        session.add(convo)

    session.commit()
    session.close()

def summarize_history(history):
    messages = [m for m in history if m["role"] != "system"]
    if not messages:
        return ""

    prompt = "Summarize the following conversation and extract user preferences:\n"
    prompt += "\n".join(f'{m["role"]}: {m["content"]}' for m in messages)

    try:
        summary_response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "You summarize conversation context for long-term memory."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=300,
            temperature=0.3
        )
        return summary_response.choices[0].message.content.strip()
    except Exception as e:
        print("Summary error:", e)
        return ""

# --------- Routes ---------

@app.route("/groupme", methods=["POST"])
def groupme_webhook():
    data = request.get_json()

    if data.get("sender_type") == "bot":
        return "Ignoring bot message", 200

    user_message = data.get("text", "")
    user_id = data.get("sender_id", "unknown")
    sender_name = data.get("name", "User")

    print(f"Received from {sender_name}: {user_message}")

    history, summary = get_user_convo(user_id)

    if not any(m["role"] == "system" for m in history):
        history.insert(0, {"role": "system", "content": "You are a helpful assistant responding in a GroupMe chat."})

    history.append({"role": "user", "content": user_message})
    history = history[-25:]

    messages = []
    if summary:
        messages.append({"role": "system", "content": f"Here is long-term memory about the user:\n{summary}"})
    messages.extend(history)

    try:
        chat_response = client.chat.completions.create(
            model="gpt-4",
            messages=messages,
            temperature=0.7,
            max_tokens=300
        )
        reply_text = chat_response.choices[0].message.content.strip()
        history.append({"role": "assistant", "content": reply_text})
        save_user_convo(user_id, history, summary)
    except Exception as e:
        print("OpenAI error:", e)
        reply_text = "⚠️ Sorry, I had trouble thinking of a response."

    try:
        response = requests.post(
            "https://api.groupme.com/v3/bots/post",
            json={"bot_id": GROUPME_BOT_ID, "text": reply_text}
        )
        print("Message sent:", response.status_code)
    except Exception as e:
        print("Failed to send message to GroupMe:", e)

    return "OK", 200

@app.route("/ping", methods=["GET"])
def ping():
    return "<h1>Ping received. The site is now running.</h1>"

@app.route("/consent")
def instructions():
    return render_template("consent.html")

if __name__ == "__main__":
    app.run(port=5000, debug=True)
