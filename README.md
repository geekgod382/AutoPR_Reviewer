# AutoPR Reviewer 🤖

AI-powered GitHub App that automatically reviews Pull Requests — detects bugs, highlights style issues, suggests performance improvements, and generates a risk score.

## Features

**Free (Basic) plan:**
- AI-powered code review (Google Gemini)
- Static analysis (flake8)
- Bug, style, and performance detection
- Risk scoring (low / medium / high)

**Pro plan ($10/mo via Dodo Payments):**
- Everything in Basic, plus:
- PR complexity score & estimated review time
- Security pattern detection (hardcoded secrets, SQL injection, `eval`/`exec`)
- Large function detection (>50 lines)
- Deeply nested loop detection (>3 levels)
- Missing error handling detection

## Quick Start

### 1. Create a GitHub App

1. Go to **Settings → Developer settings → GitHub Apps → New GitHub App**.
2. Set the **Webhook URL** to your server's public URL + `/webhook` (e.g. `https://your-domain.com/webhook`).
3. Generate and save a **webhook secret**.
4. Under **Permissions**, grant:
   - **Pull requests**: Read & Write
   - **Contents**: Read-only
5. Subscribe to the **Pull request** event.
6. Generate a **private key** and download the `.pem` file.
7. Note your **App ID** from the app settings page.

### 2. Configure Environment

Copy the example env file and fill in your values:

```bash
cp .env.example .env
```

| Variable | Description |
|---|---|
| `GITHUB_APP_ID` | Your GitHub App's ID |
| `GITHUB_PRIVATE_KEY_PATH` | Path to the `.pem` private key file |
| `GITHUB_WEBHOOK_SECRET` | The webhook secret you set in the GitHub App |
| `GEMINI_API_KEY` | Google Gemini API key ([get one here](https://aistudio.google.com/apikey)) |
| `DODO_PAYMENTS_API_KEY` | *(optional)* Dodo Payments API key for Pro subscriptions |
| `DODO_WEBHOOK_SECRET` | *(optional)* Dodo webhook signature secret |
| `DATABASE_URL` | SQLite URL (default: `sqlite:///./autopr.db`) |

### 3. Run Locally

```bash
# Install dependencies
pip install -r requirements.txt

# Start the server
uvicorn app.main:app --reload --port 8000
```

Use a tool like [ngrok](https://ngrok.com/) to expose your local server:

```bash
ngrok http 8000
```

Then update your GitHub App's webhook URL to the ngrok URL + `/webhook`.

### 4. Run with Docker

```bash
# Build and start
docker compose up --build -d

# View logs
docker compose logs -f app
```

Make sure your `.env` file and `private-key.pem` are in the project root.

## Project Structure

```
AutoPR-Reviewer/
├── app/
│   ├── main.py              # FastAPI entry point
│   ├── config.py            # Settings (pydantic-settings)
│   ├── auth.py              # GitHub App JWT auth
│   ├── webhook.py           # Webhook endpoint + signature verification
│   ├── github_client.py     # GitHub API calls (diff, files, comments)
│   ├── reviewer.py          # Orchestrator — runs all analyzers
│   ├── models.py            # SQLAlchemy models
│   ├── database.py          # DB engine + session
│   ├── payments.py          # Dodo Payments webhook + plan lookup
│   └── analyzer/
│       ├── ai.py            # Gemini-based AI review
│       ├── static.py        # flake8 static analysis
│       ├── risk.py          # Risk score calculation
│       └── premium.py       # Pro-only: security, complexity, etc.
├── tests/
│   ├── test_webhook.py
│   ├── test_analyzer.py
│   └── test_reviewer.py
├── .env.example
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
└── README.md
```

## Running Tests

```bash
pip install pytest
pytest tests/ -v
```

## API Endpoints

- `POST /webhook` — GitHub webhook receiver
- `POST /payments/webhook` — Dodo Payments webhook receiver
- `GET /health` — Health check

## How It Works

1. A PR is opened or updated on a repo with the GitHub App installed.
2. GitHub sends a webhook event to `/webhook`.
3. The app verifies the signature, fetches the PR diff and file list.
4. It runs static analysis (flake8) and AI analysis (Gemini) in parallel.
5. A risk score is calculated based on file count, change volume, sensitive files, and findings.
6. If the installation is on the Pro plan, premium analysis is also run (complexity, security patterns, etc.).
7. A formatted Markdown review comment is posted on the PR.

## License

MIT
