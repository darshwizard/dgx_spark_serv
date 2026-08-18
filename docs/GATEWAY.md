# A single-model serving gateway for the DGX Spark

The Spark hosts **one model at a time** (unified memory forces it — see
[OPERATIONS.md](OPERATIONS.md)), but callers want a stable endpoint that doesn't
change when you swap models every few days. A thin gateway in front of the live
backend solves this. This is the design we run; the pieces below are the ones
worth stealing.

## Shape

```
  apps ──HTTP──▶  gateway :8080  ──proxy──▶  live backend (vLLM/SGLang) :<port>
                  (host network,            one at a time; swapped by an
                   OpenAI-compatible)       arbitration script, gpu.sh)
```

- The gateway holds a small catalog: `backend name → {base_url, prefix, model names}`.
- A swap script (`gpu.sh`) stops the old container, starts the new one, then POSTs
  the new active backend name to the gateway's `/admin/active`. The gateway only
  ever forwards to the **declared active** backend — never one it discovers by
  probing, so a health blip can't silently reroute traffic to the wrong model.

## Four features that make it pleasant to call

### 1. `auto` — a model name that never goes stale
`/v1/models` advertises a synthetic `auto` entry (listed first) alongside the real
model id. `auto` always resolves to whatever is live, so an app saves `model: "auto"`
once and never edits config on a swap. The completion response's `model` field still
reports the concrete model that answered, so traces stay honest.

### 2. Reroute instead of 404 on a stale name
A caller asking for a known-but-inactive model gets routed to the active one and
**told** so via `X-Gateway-Rerouted-From` / `X-Gateway-Served-Model` response headers
(and a prepended system note). A stale model name in someone's config becomes a
warning, not a failed request. Set `GATEWAY_REROUTE_INACTIVE=0` to disable this while
benchmarking, where a silent substitution would misattribute one model's numbers.

### 3. Soft auth = identity without secret-management
The bearer token is treated as an **identity, not a secret**. The gate accepts either
a configured key *or* any self-identifying plain label (`[A-Za-z0-9][A-Za-z0-9._-]{0,31}`),
and rejects only missing/garbage tokens:

```python
if API_KEYS and request.url.path not in OPEN_PATHS:
    key = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    if key not in API_KEYS and not CLIENT_TOKEN_RE.fullmatch(key):
        return _401()
```

A new app calls in by sending `Authorization: Bearer <its-own-name>` — no key to
provision, no coordination — and is attributed correctly in the usage meter. This is
**identity, not security**: anyone who names themselves gets in, which is the right
trade *only* on a trusted LAN. To harden back to strict keys, drop the
`CLIENT_TOKEN_RE` branch. `OPEN_PATHS` (`/health`, `/`, `/v1/models`) stay keyless so
endpoint verification and model discovery work without auth; inference and the usage
stats do not.

### 4. Stable caller identity in the meter
Every call is attributed without the caller doing anything special:
- bearer is a known/plain label → logged as that name;
- bearer is an opaque credential → logged as a stable `tok:<sha256[:8]>` (never stored
  raw, because the stats DB is a plain file that gets copied around);
- no bearer → falls back to `ua:<User-Agent>`, else `anon`.

An optional `X-Session-Id` (or `X-Conversation-Id`) header groups a run's turns exactly,
instead of guessing session boundaries from inter-call gaps.

## Client contract (what to hand an app)

```
Base URL:  http://<SPARK-IP>:8080/v1
Auth:      Authorization: Bearer <your-app-name>     # identity, not a secret
Model:     auto                                       # follows every swap
Format:    OpenAI-compatible (POST /v1/chat/completions, GET /v1/models, GET /health)
```

Rules worth stating to callers: send `auto` (never a hardcoded id); read `response.model`
to log what served; retry with backoff on **503** (returned during the ~5–15 min a swap
takes to boot the next model); thinking is often on by default and backends run
~20–85 tok/s, so use long timeouts and `max_tokens >= 512`.

## Notes for anyone adapting this

- Keys live in the runtime env (`GATEWAY_API_KEYS`), not in code — so a `.env` with real
  values never enters version control. The behavior (`auto`, open `/v1/models`, soft auth,
  reroute) lives in the app and is safe to publish.
- Bind to loopback for a single-user box; only bind to the LAN with auth on. A LAN bind
  plus soft auth is identity-grade, not security-grade — fine behind a trusted network,
  not on anything internet-reachable.
