import os
from dotenv import load_dotenv
from flask import Flask, request
import requests
from openai import OpenAI

# Load environment variables from .env file
load_dotenv()

# Create Flask app
app = Flask(__name__)

# Load API keys from .env
GROUPME_BOT_ID = os.getenv("GROUPME_BOT_ID")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Initialize OpenAI client (for SDK v1+)
client = OpenAI(api_key=OPENAI_API_KEY)

@app.route("/groupme", methods=["POST"])
def groupme_webhook():
    data = request.get_json()

    # Prevent bot from replying to itself
    if data.get("sender_type") == "bot":
        return "Ignoring bot message", 200

    user_message = data.get("text", "")
    sender_name = data.get("name", "User")

    print(f"Received from {sender_name}: {user_message}")

    # Ask OpenAI for a reply
    try:
        chat_response = client.chat.completions.create(
            model="gpt-4",  # or "gpt-3.5-turbo" if preferred
            messages=[
                {"role": "system", "content": "You are a helpful assistant responding in a GroupMe chat."},
                {"role": "user", "content": user_message}
            ],
            temperature=0.7,
            max_tokens=300
        )
        reply_text = chat_response.choices[0].message.content.strip()
    except Exception as e:
        print("OpenAI error:", e)
        reply_text = "⚠️ Sorry, I had trouble thinking of a response."

    # Send reply to GroupMe
    try:
        response = requests.post(
            "https://api.groupme.com/v3/bots/post",
            json={
                "bot_id": GROUPME_BOT_ID,
                "text": reply_text
            }
        )
        print("Message sent:", response.status_code)
    except Exception as e:
        print("Failed to send message to GroupMe:", e)

    return "OK", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
