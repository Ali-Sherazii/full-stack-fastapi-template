# Code Obfuscation

I took the official FastAPI + React (Vite) full-stack template and added two protection layers to its Docker build, so every image ships hardened automatically. No source changes to the app logic itself everything happens between "build" and "ship."

1. **Frontend obfuscation** — a Vite build plugin runs `javascript-obfuscator` over each compiled chunk after minification. Identifiers get renamed to hex, string literals are pulled into a shuffled base64-encoded array, and the code gets control-flow flattening + dead-code injection. *(Self-defending mode had to stay off — TanStack Router's route-based code splitting means chunks call into each other via dynamic `import()`, and self-defending assumes one self-contained file; it broke cross-chunk calls.)*

2. **Backend obfuscation** — a build stage runs `pyarmor` over the FastAPI source. Every obfuscated module becomes an encrypted binary blob loaded through a small native runtime (a compiled `.so`), so **no readable Python text ships for that code either** — unlike the JS layer, this isn't a separate text-transform-then-compile step, PyArmor does both in one pass. *(Alembic's migration scripts, and the three bootstrap scripts `prestart.sh` runs directly as `python foo.py` instead of importing, had to stay unobfuscated — PyArmor's package-relative runtime import only resolves on `import`, not on a standalone script run, and none of those files hold logic worth protecting.)*


The final image contains the obfuscated frontend bundle, the PyArmor-protected backend package, and the untouched non-code assets (email templates, Alembic migrations, static frontend files). **None of the plain backend `.py` source for protected modules is in the shipped image** — the multi-stage build copies forward only the obfuscated output; the stage that briefly held plaintext never becomes a layer of the final image.

- **Protected:** all FastAPI route/business logic (`api/`, `core/`, `crud.py`, `models.py`, `main.py`, `utils.py`); all frontend app code.
- **Not protected (by design):** Alembic migrations and the three direct-run bootstrap scripts (no business logic in them, and obfuscating them breaks how they're invoked); client-side JS is still readable in the end — it executes in the user's browser, so obfuscation raises the cost of reading it but can't hide it; third-party `node_modules`/site-packages (public code, not ours).

## Verified

- Full multi-stage Docker build succeeds and reproduces cleanly.
- App behaves identically after obfuscation: health check, OpenAPI schema generation (all 15 routes present), and frontend serving all return the same as the stock build.
- Tested the write path, not just page loads: signed up a user (DB insert + password hashing through obfuscated `crud.py` / `core/security.py`), then logged in and got back a valid JWT (through obfuscated `core/security.py` / `api/deps.py`).
- Headless-browser test of the real login flow — obfuscated frontend calling the obfuscated backend — form renders, submits, redirects on success, zero console errors, zero failed requests.
- Confirmed the full deployment bootstrap against a genuinely fresh database volume: `backend_pre_start.py` (wait-for-db) → `alembic upgrade head` (all 5 migrations) → `initial_data.py` (seed superuser), all running against the obfuscated package — then logged in as that seeded superuser.
- Along the way, caught and fixed a real regression this obfuscation introduced (PyArmor's relative runtime import breaking on directly-run scripts) by re-testing that exact bootstrap path instead of stopping at the app's normal `import`-based startup.

Stacking these raises the **cost** of reverse-engineering — an attacker has to defeat PyArmor's runtime before the backend logic is readable at all, and deobfuscate the JS separately for the frontend — but this is deterrence, not a cryptographic guarantee, and should be backed by real license terms. Worth flagging on its own: PyArmor's free tier is licensed for use only until a product's sales exceed "100× the license fee," after which it expects a paid license so probably for our project we would have to take the premier license.

## stronger protection

If we dont want to actually buy it for the project what we can do is move the few genuinely sensitive functions  out of Python into a **native extension (Rust via PyO3, or a compiled C extension)** since reversing machine code is a different league than reversing even encrypted bytecode.

## Repo & how to run

Repo: changes are local only, not yet pushed to a fork — `origin` currently points at the upstream `https://github.com/fastapi/full-stack-fastapi-template`. Changes are in `backend/Dockerfile`, `frontend/vite.config.ts`, `frontend/package.json`, `bun.lock`, and one unrelated pre-existing syntax bug fixed along the way in `backend/app/api/deps.py`.

```
docker compose up -d --build db backend   # app at http://localhost:8000, API docs at /docs
```
