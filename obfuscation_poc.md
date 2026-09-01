# Code Obfuscation

I took the official FastAPI + React (Vite) full-stack template and added two protection layers to its Docker build, so every image ships hardened automatically. No source changes to the app logic itself - everything happens between "build" and "ship," aside from two small compatibility fixes described below.

1. **Frontend obfuscation** — a Vite build plugin runs `javascript-obfuscator` over each compiled chunk after minification. Identifiers get renamed to hex, string literals are pulled into a shuffled base64-encoded array, and the code gets control-flow flattening + dead-code injection. *(Self-defending mode had to stay off — TanStack Router's route-based code splitting means chunks call into each other via dynamic `import()`, and self-defending assumes one self-contained file; it broke cross-chunk calls.)*

2. **Backend obfuscation** — a build stage runs `Cython` over the FastAPI source, compiling each module to C and then to a platform-native extension (`.so`), in place, then deletes the `.py` it came from. This was originally PyArmor (encrypted bytecode blobs behind a small runtime); it's now Cython instead: a genuine compile to machine code rather than an encrypted-but-still-Python-bytecode blob, and it sidesteps PyArmor's free-tier licensing ceiling entirely.

The final image contains the obfuscated frontend bundle, the Cython-compiled backend package, and the untouched non-code assets (email templates, Alembic migrations, static frontend files, `app/models.py`). **None of the plain backend `.py` source for compiled modules is in the shipped image** — the multi-stage build copies forward only `/src/app` from the obfuscate stage, which by that point holds only compiled `.so` files plus whatever was deliberately never fed to Cython; the stage that briefly held the plaintext `.py` for compiled modules never becomes a layer of the final image.

- **Protected (compiled to native code):** `api/` (routes and deps), `core/config.py`, `core/db.py`, `core/security.py`, `crud.py`, `main.py`, `utils.py`; all frontend app code.
- **Not protected (by design):** Alembic migrations and the three direct-run bootstrap scripts (no business logic in them, and compiling them breaks how they're invoked — see `cythonize_build.py`); `app/models.py` (see below); client-side JS is still readable in the end since it executes in the user's browser — obfuscation raises the cost of reading it but can't hide it; third-party `node_modules`/site-packages (public code, not ours).

## Why Cython instead of PyArmor

PyArmor's free tier is licensed for use only until a product's sales exceed "100× the license fee," after which it expects a paid license — the honest reading of that is a real per-project premium license eventually. Cython has no such ceiling: it's a genuine ahead-of-time compiler (BSD-licensed), and the output is actual machine code, not Python bytecode wrapped in an encryption layer with a runtime that unwraps it. That's a strictly harder reverse-engineering target than PyArmor's approach, at zero licensing cost.

The tradeoff is compatibility risk: Cython changes how annotations and some object internals behave, and a framework as introspection-heavy as FastAPI + Pydantic + SQLModel can hit real incompatibilities. Two showed up during testing (both documented in `cythonize_build.py` and fixed):

1. **`@computed_field` on a bare `@property`** (`core/config.py`, `emails_enabled`) — Cython stores the property getter's return annotation as an unevaluated string rather than the real `bool` object, and Pydantic's schema builder requires the real type. Fixed with one line: `@computed_field(return_type=bool)`, which is Pydantic's own documented workaround for exactly this ambiguity.
2. **`app/models.py`'s circular relationship** (`User.items: list[Item]`, `Item.owner: User`) — one side always forward-references a class that isn't defined yet at annotation-evaluation time. Cython's fallback for an unresolvable annotation is to freeze the *entire* expression (`"list[Item]"`) into one opaque string, rather than only deferring the inner class name the way CPython's own evaluation does. SQLAlchemy's relationship resolver needs the container (`list[...]`) to be a real, evaluated generic with only the inner name deferred, and can't parse Cython's frozen-whole-expression form — no source-level rewrite of the annotation (quoting the inner name, explicit `Mapped[list[...]]`) changes this, since the underlying shape Cython produces is the same either way. `models.py` is excluded from compilation as a result: it's pure schema (field names/types), already fully visible through the API's own OpenAPI output regardless of whether the source is obfuscated, so nothing of real value is lost by leaving it as plain Python.

Also needed: `annotation_typing: False` in Cython's compiler directives project-wide, restoring normal eager annotation evaluation (Cython's default instead freezes *all* annotations to strings, which independently breaks SQLModel/SQLAlchemy's normal relationship handling even for non-circular cases).

## Verified

`docker compose build backend` and `docker compose up -d db backend`, using the actual `backend/Dockerfile` end to end.

- `cythonize_build.py` runs clean in the real `backend-obfuscate` build stage, compiling every non-excluded module to a native `.so` with no errors, then deleting the `.py`/`.c` it came from. Confirmed inside the built image (`docker run --rm backend:latest find /app/backend/app ...`) that only compiled `.so` files, `models.py`, the three bootstrap scripts, Alembic, and static assets are present — no plaintext source for any compiled module.
- The real Docker build surfaced one more issue neither the WSL proxy run nor the isolated smoke tests caught: `uv sync --package app` (hatchling) failed with *"Unable to determine which files to ship... no directory that matches the name of your project (app)"*. Hatchling's default wheel file-selection heuristic looks for `app/__init__.py` to recognize `app` as the package to include, and Cython had replaced it with `app/__init__.cpython-314-x86_64-linux-gnu.so`. Fixed by adding an explicit `[tool.hatch.build.targets.wheel] packages = ["app"]` to `backend/pyproject.toml`, rather than exempting another file from compilation.
- `docker compose up -d db backend` against a fresh Postgres volume, containers report `healthy`.
- Ran the actual deployment bootstrap inside the running container — `backend_pre_start.py` (wait-for-db) → `alembic upgrade head` (all 5 migrations) → `initial_data.py` (seed superuser) — against real Postgres, all uncompiled scripts, all succeeded.
- Hit the live API over real HTTP end to end: `GET /openapi.json` (15 routes), `POST /users/signup` (password hashing through compiled `core/security.py`, DB insert through compiled `crud.py`, into real Postgres), `POST /login/access-token` (JWT issuance through compiled `core/security.py`), authenticated `GET /users/me` (full `Annotated[..., Depends(...)]` dependency chain through compiled `api/deps.py`), rejection of a missing token (401), and `POST`/`GET /items/` (the `User`↔`Item` relationship end to end, through compiled `api/routes/items.py` against the uncompiled `models.py`).
- Isolated, reproducible repros for both Cython compatibility issues (`computed_field`, the circular relationship), each confirmed against the *uncompiled* source in the same environment to rule out anything other than Cython being the cause before changing anything.

**Not verified:** the frontend calling the compiled backend through an actual browser (frontend obfuscation itself was verified separately, prior to the Cython switch, and is untouched by this change).

## stronger protection

If the goal is to go further than Cython, the next step up is the same one that applied to PyArmor: move the few genuinely sensitive functions out of Python entirely into a **native extension (Rust via PyO3, or a hand-written C extension)**, hand-written rather than transpiled. Cython's C output is still mechanically derived from the Python source and is more reversible than code written to be a native extension from the start.

## Repo & how to run

Repo: changes are local only, not yet pushed to a fork — `origin` currently points at the upstream `https://github.com/fastapi/full-stack-fastapi-template`. Changes are in `backend/Dockerfile`, `backend/cythonize_build.py` (new), `backend/app/core/config.py` (one-line Cython-compatibility fix), `backend/pyproject.toml` (explicit hatchling wheel package list), `frontend/vite.config.ts`, `frontend/package.json`, `bun.lock`, and one unrelated pre-existing syntax bug fixed along the way in `backend/app/api/deps.py`.

```
docker compose up -d --build db backend   # app at http://localhost:8000, API docs at /docs
```
