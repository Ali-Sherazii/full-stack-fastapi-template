FROM oven/bun:1 AS frontend-build

WORKDIR /app

COPY package.json bun.lock /app/
COPY frontend/package.json /app/frontend/

WORKDIR /app/frontend

RUN bun install

COPY ./frontend /app/frontend

ARG VITE_API_URL=

RUN bun run build


FROM python:3.14 AS backend-obfuscate

RUN pip install --no-cache-dir pyarmor==9.2.6

WORKDIR /src

COPY ./backend/app ./app

# Obfuscate everything except:
# - the Alembic migrations, which Alembic reads and lists by filename and
#   don't need protecting
# - backend_pre_start.py/initial_data.py/tests_pre_start.py, which prestart.sh
#   and tests-start.sh run directly as `python app/foo.py` rather than
#   importing as `app.foo`; PyArmor's package-relative runtime import only
#   resolves when the file is imported, not run standalone, and these hold no
#   logic worth protecting anyway
RUN pyarmor gen -O /obfuscated -i --prefix app --enable jit -r \
    --exclude "app/alembic*" \
    --exclude "app/backend_pre_start.py" \
    --exclude "app/initial_data.py" \
    --exclude "app/tests_pre_start.py" \
    app


FROM python:3.14

ENV PYTHONUNBUFFERED=1

# Install uv
# Ref: https://docs.astral.sh/uv/guides/integration/docker/#installing-uv
COPY --from=ghcr.io/astral-sh/uv:0.9.26 /uv /uvx /bin/

# Compile bytecode
# Ref: https://docs.astral.sh/uv/guides/integration/docker/#compiling-bytecode
ENV UV_COMPILE_BYTECODE=1

# uv Cache
# Ref: https://docs.astral.sh/uv/guides/integration/docker/#caching
ENV UV_LINK_MODE=copy

WORKDIR /app/

# Place executables in the environment at the front of the path
# Ref: https://docs.astral.sh/uv/guides/integration/docker/#using-the-environment
ENV PATH="/app/.venv/bin:$PATH"

# Install dependencies
# Ref: https://docs.astral.sh/uv/guides/integration/docker/#intermediate-layers
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-workspace --package app

COPY ./backend/scripts /app/backend/scripts

COPY ./backend/pyproject.toml ./backend/alembic.ini /app/backend/

COPY --from=backend-obfuscate /obfuscated/app /app/backend/app

COPY ./backend/app/alembic /app/backend/app/alembic

COPY ./backend/app/email-templates /app/backend/app/email-templates

COPY ./backend/app/backend_pre_start.py ./backend/app/initial_data.py ./backend/app/tests_pre_start.py /app/backend/app/

COPY --from=frontend-build /app/backend/app/frontend /app/backend/app/frontend

# Sync the project
# Ref: https://docs.astral.sh/uv/guides/integration/docker/#intermediate-layers
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --package app

WORKDIR /app/backend/

CMD ["fastapi", "run", "--workers", "4"]
