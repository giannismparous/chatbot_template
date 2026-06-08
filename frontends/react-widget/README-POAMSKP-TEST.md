# POAMSKP production widget — local test harness

React widget at `frontends/react-widget` pointed at the live Cloud Run API.

## Env (`.env` or `.env.local`, gitignored)

```env
VITE_CHATBOT_API_BASE=https://simasia-chatbot-api-tqdnz23eua-ew.a.run.app
VITE_CLIENT_ID=default
VITE_CLIENT_KEY=wk_<your widget key>
VITE_CHAT_API_VERSION=v2
VITE_CHAT_STREAMING=true
VITE_SESSION_STORAGE=session
```

## Localhost and origin binding

Production widget keys are bound to:

- `https://www.poamskp.gr`
- `https://poamskp.gr`

**`npm run dev` on `http://localhost:5173` will get 403** unless you rotate a **temporary test key** with `http://localhost:5173` (and optionally `http://127.0.0.1:5173`) in `allowed_origins`. Do not bypass origin checks in the frontend.

## Run locally

```bash
cd frontends/react-widget
npm install
npm run dev
```

Open http://localhost:5173 — only works with a localhost-allowed widget key.

## Build static test bundle

```bash
npm run build
npm run preview   # serves dist/ on http://localhost:4173 — same origin restriction
```

## API contract

- `POST /v2/chat/respond`
- Header: `x-client-key: <VITE_CLIENT_KEY>`
- Body: `{ client_id, message, stream, session_id?, mode, top_k }`

## Smoke test (curl, bypasses browser but needs allowed Origin header)

```bash
curl -sS -X POST "https://simasia-chatbot-api-tqdnz23eua-ew.a.run.app/v2/chat/respond" \
  -H "Content-Type: application/json" \
  -H "x-client-key: wk_YOUR_KEY" \
  -H "Origin: https://www.poamskp.gr" \
  -d '{"client_id":"default","message":"Πώς μπορώ να επικοινωνήσω με την ΠΟΑμΣΚΠ;","stream":false,"mode":"hybrid_local","top_k":6}'
```

Expected answer includes POAMSKP contact details (phone, email, address, website).
