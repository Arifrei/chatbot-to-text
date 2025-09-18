# WARP.md

This file provides guidance to WARP (warp.dev) when working with code in this repository.

## Project Overview

This is a Python Flask application that serves as an AI-powered chatbot for GroupMe and SMS messaging platforms. The bot uses OpenAI's GPT-4 model to generate responses and maintains conversation history in a PostgreSQL database.

### Architecture

The application consists of two main components:

1. **GroupMe Bot** (`main.py`): Full-featured bot with conversation history, webhooks, and polling
2. **SMS Bot** (`signalwire_test.py`): Simplified SMS webhook handler for SignalWire/Twilio

**Key architectural patterns:**
- Single-file Flask applications for simplicity
- Database retry decorators for connection resilience
- Background polling thread for missed messages
- Conversation summarization for long-term memory management
- Environment-based configuration

### Database Schema

The application uses PostgreSQL with two tables:
- `conversations`: Stores per-user conversation history and AI-generated summaries
- `group_checkpoints`: Tracks last processed message ID for polling

## Development Commands

### Environment Setup
```powershell
# Create virtual environment
python -m venv .venv

# Activate virtual environment
.\.venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt
```

### Running the Application
```powershell
# Run main GroupMe bot (development mode with auto-reload)
python main.py

# Run SMS bot
python signalwire_test.py
```

### Testing
```powershell
# Test webhook endpoints
Invoke-RestMethod -Uri "http://localhost:5000/ping" -Method Get

# Test GroupMe webhook (requires JSON payload)
$body = @{
    sender_type = "user"
    text = "Hello bot"
    sender_id = "12345"
    name = "Test User"
    group_id = "group123"
    id = "msg456"
} | ConvertTo-Json

Invoke-RestMethod -Uri "http://localhost:5000/groupme" -Method Post -Body $body -ContentType "application/json"
```

### Database Operations
```powershell
# Connect to database (requires DATABASE_URL environment variable)
# Tables are auto-created on application startup via init_db()
```

## Environment Variables

Required environment variables in `.env` file:

**GroupMe Bot:**
- `GROUPME_BOT_ID`: Bot ID from GroupMe developer console
- `GROUPME_ACCESS_TOKEN`: API token for GroupMe
- `GROUPME_GROUP_ID`: Target group ID for polling
- `OPENAI_API_KEY`: OpenAI API key
- `DATABASE_URL`: PostgreSQL connection string (with SSL)
- `FLASK_SECRET_KEY`: Flask session secret
- `POLL_INTERVAL_SECONDS`: Polling frequency (default: 10)
- `PORT`: Server port (default: 5000)
- `LOG_LEVEL`: Logging level (default: INFO)

**SMS Bot:**
- `OPENAI_API_KEY`: OpenAI API key
- `PORT`: Server port (default: 5000)

## Key Components

### Conversation Management
- **History Limit**: 20 messages per user (older messages get summarized)
- **Context Window**: Last 25 messages sent to OpenAI
- **Summarization**: Automatic conversation summarization when history exceeds limit
- **Memory**: Long-term memory via AI-generated summaries

### Error Handling
- Database connection retry with exponential backoff
- Graceful degradation for API failures
- Comprehensive logging for debugging

### Polling vs Webhooks
- **Webhooks**: Real-time message processing via `/groupme` endpoint
- **Polling**: Background thread catches missed messages using checkpoints
- **Dual Mode**: Both methods work simultaneously for reliability

### Message Processing Flow
1. Receive message (webhook or polling)
2. Load user conversation history and summary
3. Prepare context for OpenAI (system prompt + summary + recent history)
4. Generate AI response using GPT-4
5. Save updated conversation history
6. Post response to GroupMe/SMS

## File Structure

- `main.py`: Main GroupMe bot application
- `signalwire_test.py`: SMS bot for SignalWire/Twilio
- `requirements.txt`: Python dependencies
- `templates/consent.html`: SMS consent form template
- `.env`: Environment variables (not tracked in git)
- `.venv/`: Python virtual environment (not tracked in git)

## Development Notes

- Uses SQLAlchemy with PostgreSQL for production deployment
- Flask debug mode enables auto-reload during development
- Background polling thread only starts in non-debug or reloader child processes
- Database connections use SSL (`sslmode=require`)
- OpenAI temperature set to 0.7 for conversational responses, 0.3 for summaries