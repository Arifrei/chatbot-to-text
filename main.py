import os
import json
import time
import threading
import logging
from dotenv import load_dotenv
from flask import Flask, request, render_template_string
import requests
from openai import OpenAI
from sqlalchemy import create_engine, Column, String, Text
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.exc import OperationalError, DBAPIError

load_dotenv()

GROUPME_BOT_ID = os.getenv("GROUPME_BOT_ID2")
GROUPME_ACCESS_TOKEN = os.getenv("GROUPME_ACCESS_TOKEN")
GROUPME_GROUP_ID = os.getenv("GROUPME_GROUP_ID2")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")
POLL_INTERVAL_SECONDS = int(os.getenv("POLL_INTERVAL_SECONDS", "10"))

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("groupme-bot")

client = OpenAI(api_key=OPENAI_API_KEY)

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY", "replace-me")

Base = declarative_base()
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=300,
    connect_args={"sslmode": "require"}
)
SessionLocal = sessionmaker(bind=engine)

class Conversation(Base):
    __tablename__ = 'conversations'
    user_id = Column(String, primary_key=True)
    history = Column(Text)
    summary = Column(Text)

class GroupCheckpoint(Base):
    __tablename__ = 'group_checkpoints'
    group_id = Column(String, primary_key=True)
    last_message_id = Column(String)

def init_db():
    Base.metadata.create_all(bind=engine)

init_db()

def db_retry(fn):
    def wrapper(*args, **kwargs):
        for attempt in (1, 2):
            s = SessionLocal()
            try:
                return fn(s, *args, **kwargs)
            except (OperationalError, DBAPIError) as e:
                s.rollback()
                logger.warning("%s DB error (attempt %s): %s", fn.__name__, attempt, e)
                engine.dispose()
                time.sleep(0.2)
            finally:
                s.close()
        if fn.__name__ in ("get_user_convo", "_get_checkpoint"):
            return ([], "") if fn.__name__ == "get_user_convo" else None
    return wrapper

@db_retry
def get_user_convo(s, user_id):
    conv = s.query(Conversation).filter_by(user_id=user_id).first()
    if conv:
        return json.loads(conv.history), conv.summary
    return [], ""

@db_retry
def save_user_convo(s, user_id, history, summary):
    conv = s.query(Conversation).filter_by(user_id=user_id).first()
    MAX_HISTORY = 20
    if len(history) > MAX_HISTORY:
        new_summary = summarize_history(history)
        if new_summary:
            summary = (summary + "\n\n" if summary else "") + new_summary
        history = [m for m in history if m.get("role") == "system"]
    if conv:
        conv.history = json.dumps(history)
        conv.summary = summary
    else:
        conv = Conversation(user_id=user_id, history=json.dumps(history), summary=summary)
        s.add(conv)
    s.commit()

@db_retry
def _get_checkpoint(s, group_id):
    cp = s.get(GroupCheckpoint, group_id)
    if cp is None:
        cp = GroupCheckpoint(group_id=group_id, last_message_id=None)
        s.add(cp); s.commit()
    return cp.last_message_id

@db_retry
def _set_checkpoint(s, group_id, msg_id):
    cp = s.get(GroupCheckpoint, group_id)
    if cp is None:
        cp = GroupCheckpoint(group_id=group_id, last_message_id=msg_id)
        s.add(cp)
    else:
        cp.last_message_id = msg_id
    s.commit()

def summarize_history(history):
    messages = [m for m in history if m.get("role") != "system"]
    if not messages:
        return ""
    prompt = "Summarize the following conversation and extract user preferences:\n" + \
             "\n".join(f'{m["role"]}: {m["content"]}' for m in messages)
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
        return (summary_response.choices[0].message.content or "").strip()
    except Exception as e:
        logger.exception("Summary error: %s", e)
        return ""

def ai_reply(messages):
    try:
        chat_response = client.chat.completions.create(
            model="gpt-4",
            messages=messages,
            temperature=0.7,
            max_tokens=300
        )
        return (chat_response.choices[0].message.content or "").strip()
    except Exception as e:
        logger.exception("OpenAI error: %s", e)
        return "⚠️ Sorry, I had trouble thinking of a response."

def groupme_post(text):
    try:
        r = requests.post(
            "https://api.groupme.com/v3/bots/post",
            json={"bot_id": GROUPME_BOT_ID, "text": text},
            timeout=10
        )
        logger.info("GroupMe post status=%s", r.status_code)
    except Exception as e:
        logger.exception("Failed to send message to GroupMe: %s", e)

def groupme_fetch(after_id):
    params = {"limit": 100, "token": GROUPME_ACCESS_TOKEN}
    if after_id:
        params["after_id"] = after_id
    try:
        r = requests.get(
            f"https://api.groupme.com/v3/groups/{GROUPME_GROUP_ID}/messages",
            params=params,
            timeout=10
        )
        if r.status_code == 200:
            data = r.json() or {}
            return (data.get("response") or {}).get("messages", [])
        elif r.status_code in (429, 500, 502, 503, 504):
            logger.warning("GroupMe fetch transient error: %s %s", r.status_code, r.text[:200])
            return []
        else:
            logger.error("GroupMe fetch error: %s %s", r.status_code, r.text[:200])
            return []
    except Exception as e:
        logger.exception("GroupMe fetch exception: %s", e)
        return []

def handle_incoming(user_id, sender_name, user_message):
    history, summary = get_user_convo(user_id)
    if not any(m.get("role") == "system" for m in history):
        history.insert(0, {"role": "system", "content": "You are a helpful assistant responding in a GroupMe chat."})
    history.append({"role": "user", "content": user_message})
    messages = []
    if summary:
        messages.append({"role": "system", "content": f"Here is long-term memory about the user:\n{summary}"})
    messages.extend(history[-25:])
    reply_text = ai_reply(messages)
    history.append({"role": "assistant", "content": reply_text})
    save_user_convo(user_id, history, summary)
    groupme_post(reply_text)

@app.route("/groupme", methods=["POST"])
def groupme_webhook():
    data = request.get_json() or {}
    if data.get("sender_type") == "bot":
        return "Ignoring bot message", 200
    user_message = data.get("text") or ""
    user_id = data.get("sender_id") or "unknown"
    sender_name = data.get("name") or "User"
    logger.info("Webhook: from %s: %s", sender_name, user_message)
    gid = str(data.get("group_id") or GROUPME_GROUP_ID or "")
    mid = data.get("id")
    if gid and mid:
        try:
            _set_checkpoint(gid, mid)
        except Exception as e:
            logger.warning("Checkpoint bump failed (non-fatal): %s", e)
    handle_incoming(user_id, sender_name, user_message)
    return "OK", 200

@app.route("/ping", methods=["GET", "HEAD"])
def ping():
    return "<h1>Ping received. The site is now running.</h1>"

@app.route("/consent", methods=["GET", "POST"])
def consent():
    if request.method == "POST":
        return "<h1>Thanks for your consent. You can now use the number provided to you to ask ChatGPT anything!</h1>"
    tpl = """
    <!doctype html>
    <html lang="en"><head>
      <meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
      <title>Consent</title>
      <style>
        body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Ubuntu,Cantarell,Noto Sans,sans-serif;margin:2rem;line-height:1.5}
        .card{max-width:720px;margin:auto;padding:1.5rem;border:1px solid #e5e7eb;border-radius:12px;box-shadow:0 1px 2px rgba(0,0,0,.05)}
        button{padding:.6rem 1rem;border-radius:10px;border:0;cursor:pointer}
      </style>
    </head><body>
      <div class="card">
        <h1>Consent to Chat with the Bot</h1>
        <p>By submitting the form, you consent to sending messages to the GroupMe bot which may be processed by OpenAI to generate responses.</p>
        <form method="POST"><button type="submit">I Agree</button></form>
      </div>
    </body></html>
    """
    return render_template_string(tpl)

def poll_for_missed_messages():
    if not (GROUPME_ACCESS_TOKEN and GROUPME_GROUP_ID):
        logger.warning("Polling disabled: missing GROUPME_ACCESS_TOKEN or GROUPME_GROUP_ID")
        return
    last_id = _get_checkpoint(GROUPME_GROUP_ID)
    while True:
        msgs = groupme_fetch(last_id)
        if not msgs:
            break
        for m in msgs:
            msg_id = m.get("id")
            if m.get("system") or m.get("sender_type") == "bot":
                if msg_id:
                    _set_checkpoint(GROUPME_GROUP_ID, msg_id)
                continue
            text = m.get("text") or ""
            uid = m.get("user_id") or "unknown"
            name = m.get("name") or "User"
            handle_incoming(uid, name, text)
            if msg_id:
                _set_checkpoint(GROUPME_GROUP_ID, msg_id)
        last_id = msgs[-1].get("id") if msgs else last_id
    logger.info("Initial catch-up complete. Entering continuous polling every %ss.", POLL_INTERVAL_SECONDS)
    while True:
        try:
            last_id = _get_checkpoint(GROUPME_GROUP_ID)
            msgs = groupme_fetch(last_id)
            for m in msgs:
                msg_id = m.get("id")
                if m.get("system") or m.get("sender_type") == "bot":
                    if msg_id:
                        _set_checkpoint(GROUPME_GROUP_ID, msg_id)
                    continue
                text = m.get("text") or ""
                uid = m.get("user_id") or "unknown"
                name = m.get("name") or "User"
                handle_incoming(uid, name, text)
                if msg_id:
                    _set_checkpoint(GROUPME_GROUP_ID, msg_id)
        except Exception as e:
            logger.exception("Polling loop exception: %s", e)
        time.sleep(POLL_INTERVAL_SECONDS)

if __name__ == "__main__":
    is_reloader_child = os.environ.get("WERKZEUG_RUN_MAIN") == "true"
    if is_reloader_child or not app.debug:
        threading.Thread(target=poll_for_missed_messages, daemon=True).start()
        # logger.info("Background poller thread started.")
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=True, use_reloader=True)
