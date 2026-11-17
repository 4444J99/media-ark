# Deploying media-ark (hosted SaaS)

The **free, local-first** product needs none of this — it runs today (`python -m src.platform.api_server`). This file is only about the **hosted paid** surface.

## Host: Cloudflare Containers (derived, not chosen)

The deploy host is **Cloudflare Containers**, derived from the live stack rather than picked from a menu:

- The org's live runtime is already Cloudflare (the `limen-runtime` Worker; studio/writelens/script-doctor all deploy through the same login-free path).
- The deploy credential — `CLOUDFLARE_API_TOKEN` — is **already owned and headless** (verified: `wrangler whoami` → account `CF-4444j99`, no interactive login). Nothing to mint.
- `wrangler` (4.x) has full `containers` support, and this repo's own `Dockerfile` (`python:3.11-slim` + `tesseract-ocr`) is a directly buildable image.

The earlier **Cloud Run / `GCP_SA_KEY`** path (`.github/workflows/deploy-api.yml`) is **superseded**: it was cloned from limen's own no-op deploy workflow and inherited a requirement for a credential that exists nowhere. That workflow is kept as a harmless no-op for honest history only.

## The one remaining atom: a spend, not a decision or a credential

A read-only `wrangler containers list` shows account `CF-4444j99` is on the **free** Workers plan. Cloudflare Containers requires **Workers Paid (~$5/mo)**. That is the single human atom left — a spend on an account already owned:

> Cloudflare dashboard → **Workers & Pages → Plans → Workers Paid**

It is **deliberately sequenced behind first revenue** (the live ChatGPT-Exporter first-dollar path outranks paying to host a pre-revenue product — demand before rails). This is tracked as lever **`L-MEDIA-ARK-HOST`** (limen `his-hand-levers.json`, issue #535), not as an open decision.

## Once the plan is enabled (no further decision)

```sh
# headless, using the already-hydrated CLOUDFLARE_API_TOKEN
wrangler containers build -t media-ark .
wrangler containers deploy media-ark
```

The API server also serves the dashboard (`web/`), so one container = the complete product (API + UI + `/api/license`).

## Before charging for Pro (separate, later atoms)

- **Persistence.** Container `/tmp` is ephemeral (Cloudflare Containers *and* Cloud Run) — sqlite quota/tier state resets per instance. Move the ledger to **Cloudflare R2** (matches the host) before Pro billing. Blocks Pro, not the free product.
- **MONETA licence pubkey.** Run MONETA keygen once and set `MEDIA_ARK_LICENSE_PUBKEY`; until then `/api/license` returns a graceful 503 and the free tier works.
