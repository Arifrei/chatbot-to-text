import os
from dotenv import load_dotenv
from flask import Flask, request, jsonify
from openai import OpenAI

load_dotenv()  # Load variables from .env

app = Flask(__name__)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY)

@app.route("/groupme", methods=["POST"])
def groupme_webhook():
    data = request.get_json()

    print("Received message:", data)

    user_message = data.get("text", "")

    try:
        chat_response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": user_message}
            ],
            temperature=0.7,
            max_tokens=300,
        )
        ai_text = chat_response.choices[0].message.content.strip()
        print("OpenAI response:", ai_text)
    except Exception as e:
        print("OpenAI API error:", e)
        ai_text = "Sorry, I couldn't process that."

    return jsonify({"response": ai_text})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
