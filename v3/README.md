# SQL Knowledge Base Chatbot

Ask questions about the DTR / consumer database in plain English. Sign in as an administrator
to see everything, or as a consumer to see only your own connection. The model (Amazon Bedrock)
looks things up, and also works out figures such as power factor, energy used and your share of a
transformer's load, showing the formula it used.

- **Frontend:** Next.js 14 (App Router), Tailwind, TypeScript
- **Backend:** FastAPI + LangChain tool-calling agent with per-user chat memory
- **Database:** SQLite with synthetic data shaped like your schema reference
- **Model:** Amazon Bedrock (Converse API), configured entirely from `backend/.env`

## 1. Set up

Needs Python 3.11+ and Node 18+.

Windows: double-click `setup.bat`. It installs everything and creates `backend/.env` from the template.
Otherwise:

```
cd backend
pip install -r requirements.txt
copy .env.example .env        (Mac/Linux: cp .env.example .env)

cd ../frontend
npm install
```

## 2. Configure Bedrock (`backend/.env`)

Open `backend/.env` and fill in three values. Nothing is hard-coded in the source.

| Setting | What to put |
|---|---|
| `AWS_BEARER_TOKEN_BEDROCK` | Your Bedrock API key, pasted as-is |
| `AWS_REGION` | The region where your model is enabled, e.g. `us-east-1` |
| `BEDROCK_MODEL_ID` | Model ID or inference profile ID from the Bedrock console |

Check it before starting the app:

```
cd backend
python check_bedrock.py
```

It prints what it read (never the key) and sends one test message. If the call fails it says what to fix.

Notes:
- Newer Claude models usually need the **inference profile ID** (starts with `us.`, `eu.`, `apac.` or `global.`) instead of the plain model ID.
- The model must support tool use through the Converse API.
- Short-term Bedrock keys expire (up to 12 hours). If calls start failing with a credentials message, make a new key and update `.env`.
- **Never share or commit `.env`.** It is in `.gitignore`. If a key was pasted anywhere public, revoke it and create a new one.
- Restart the backend after any change to `.env`.
- To use a local model instead: `LLM_PROVIDER=ollama`, `pip install langchain-ollama`, and set `OLLAMA_MODEL`.

Optional frontend setting: copy `frontend/.env.local.example` to `.env.local` only if the backend is not on `http://127.0.0.1:8000`.

## 3. Run

Two windows: `run_backend.bat` and `run_frontend.bat` (or `python -m uvicorn main:app --port 8000` in `backend`, and `npm run dev` in `frontend`). Open http://localhost:3000.

The first start builds `epdatalake_local.db` and the login database `app_auth.db`.

## 4. Sign in

| Who | Username | Password |
|---|---|---|
| Administrator | `admin` | `Admin@123` |
| Consumer (LT) | their SCNO, e.g. `7200003` (Ravi Patel) | `Pass@` + username, e.g. `Pass@7200003` |
| Consumer (HT) | e.g. `HT1001` | `Pass@HT1001` |

These are demo passwords. Change `ADMIN_PASSWORD` and `USER_PASSWORD_PREFIX` in `.env` before the first start, or change one account later:

```
cd backend
python auth.py --list
python auth.py --set-password 7200003
```

Right after login the model greets you automatically, using your own details (and, for the administrator, a short list of things needing attention). Five wrong passwords lock that username for a few minutes.

Interesting demo cases: `7200005` Mahesh Patel (poor power factor), `7200009` Kavitha Naidu (peak above contracted load), `7200001` Lakshmi Patel (no smart meter, monthly readings only), DTR-1006 (overloaded).

## What it can do

The model has four tools:

1. `execute_sql_query` runs a read-only SELECT.
2. `get_current_datetime` gives the date, time and time zone.
3. `calculate_metric` computes power factor, energy used, transformer utilisation / loading, share of the transformer's energy, and top consumers.
4. `calculate` evaluates plain arithmetic safely.

Administrators can ask by name ("power factor of Mahesh Patel") or by number.

## How access is enforced

Access control is in code, not in the prompt, so it holds even if the model is tricked.

- The signed-in user is stored in a context variable for the request. With nobody signed in, every tool refuses.
- A consumer's SQL runs against an in-memory copy of the database that holds **only their rows**. CTEs, `main.` prefixes, unions and subqueries therefore still return only their own data.
- Only SELECT is allowed. Writes, PRAGMA, ATTACH, `sqlite_master` and memory-hungry functions are denied, and queries time out after 5 seconds.
- Metric tools check the target too: a consumer asking for someone else's figures, or for a transformer-wide ranking, gets a refusal.
- Chat memory is keyed by `username:session`, so session IDs can't be used to read another person's chat.
- The sign-in token lives in an httpOnly cookie set by the Next.js server; browser scripts never see it. Passwords are stored as salted PBKDF2 hashes.
- Guardrails run before the model: unrelated questions (politics, weather, jokes and so on) never reach it, and consumers asking about other people get an immediate refusal. These are a convenience layer; the real limits are the ones above.

## Assumptions to know about

- Your schema reference has no active-energy column on the readings tables, but power factor needs one, so the synthetic tables have an added `wh_imp` (Wh) next to `vah_imp` (VAh). Power factor = Wh / VAh. Remove or map this to your real column when you move to the real database.
- Consumers may see their own share of their transformer's energy. Set `USERS_CAN_SEE_DTR_SHARE=false` to turn that off.
- Mobile numbers are masked in results.

## Tests

```
cd backend
python -m pytest -q
```

Covers the data, login and lockout, isolation attack queries, the calculations (checked against independent SQL), guardrails, tools, the agent loop with a scripted model, and the API. The real Bedrock call is not part of the tests; use `check_bedrock.py` for that.

## Files

```
backend/
  main.py          API endpoints: login, welcome, chat
  agent.py         system prompt, Bedrock/Ollama setup, tool-calling loop, memory
  tools.py         the four tools
  metrics.py       power factor, energy, utilisation, share, ranking
  calculator.py    safe arithmetic
  access.py        per-user database view and read-only execution
  auth.py          accounts, sessions, lockout (also a small CLI)
  context.py       the signed-in user for the current request
  guardrails.py    input cleaning, relevance and scope checks, SQL validation
  user_profile.py  the details used for the login greeting
  database.py      schema and synthetic data
  config.py        reads backend/.env
  check_bedrock.py tests your Bedrock settings
frontend/
  app/login        sign-in page
  app/api          proxy routes that attach the cookie token
  middleware.ts    sends signed-out visitors to /login
  components       sidebar, messages, SQL, tables, calculation cards
```
