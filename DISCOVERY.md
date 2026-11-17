# Discovery: organvm/media-ark

**Date:** 2026-06-23
**Verdict:** Promote — real, near-release product with a clear revenue path

## Value Thesis

Media Ark is a local-first media archive pipeline for images, video, PDFs, and documents, currently at v0.2.0 Beta (Stage 4/5: Verification + Release prep). The implementation is substantial: a 3,400-line Python core engine that covers ingest → deduplicate → process → OCR/enrich → index → verify/repair, backed by a full platform layer — REST API, MCP stdio server, web dashboard, auth, Stripe billing, subscription records, and an encrypted-cloud-sync scaffold. The product has a registered domain (media-ark.org), a two-tier model (Free: local-only; Pro: $7/mo encrypted cloud sync and backup), and Stripe webhooks already wired to subscription state. Its highest latent value is the MCP server, which exposes five tools (`capture_status`, `capture_check`, `capture_run`, `capture_verify`, `capture_query`) that let any MCP-capable Claude agent query and operate the archive programmatically — making it the natural evidence-and-source-material layer for AI-assisted knowledge work, journalism, and research workflows in the estate. One P0 item remains on the roadmap (run-time install/deploy hardening), and a single clear revenue unlock is outstanding: the cloud-sync encryption in `src/platform/sync.py` uses a SHA-256 keystream XOR placeholder that is self-documented as not production-grade. Replacing it with AES-256-GCM via the `cryptography` library is the change that makes the Pro sync production-safe and activates the $7/mo subscription path.

**Best concrete first task:** Swap the stub XOR cipher in `src/platform/sync.py:encrypt_before_upload` / `decrypt_after_download` for real AES-256-GCM via the `cryptography` library, making the encrypted cloud sync production-safe and unlocking the Pro tier revenue path.
