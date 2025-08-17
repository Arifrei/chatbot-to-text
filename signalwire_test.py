import os
from flask import Flask, request, Response
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
app = Flask(__name__)
client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

SYSTEM_PROMPT = "You are a concise, helpful SMS assistant. Keep replies under 600 characters."

def xml_message(text: str) -> Response:
    # Return LaML XML so SignalWire auto-sends the SMS reply
    def esc(s: str) -> str:
        return (s.replace("&", "&amp;")
                 .replace("<", "&lt;")
                 .replace(">", "&gt;")
                 .replace('"', "&quot;")
                 .replace("'", "&apos;"))
    xml = f'<?xml version="1.0" encoding="UTF-8"?><Response><Message>{esc(text)}</Message></Response>'
    return Response(xml, mimetype="application/xml")

@app.post("/sms")
def sms_webhook():
    # SignalWire posts form-encoded fields: Body, From, To, MessageSid, etc.
    body = (request.form.get("Body") or "").strip()
    # Simple compliance keywords
    up = body.upper()
    if up == "STOP":
        return xml_message("You’re opted out. Reply START to opt back in.")
    if up in ("HELP", "INFO"):
        return xml_message("AI SMS bot. Text questions to chat. Reply STOP to opt out.")

    # Call OpenAI and reply
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": body},
            ],
            temperature=0.5,
            max_tokens=300,
        )
        reply = (resp.choices[0].message.content or "").strip()
    except Exception as e:
        reply = "Sorry—had an issue generating a reply. Try again."

    return xml_message(reply)

@app.get("/")
def health():
    return "OK"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=True)
