#!/bin/bash
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)
#
# SessionStart hook for Claude Code on the web.
#
# The documented local setup (README, CLAUDE.md) is Docker Compose, but the
# web sandbox has no Docker daemon — so this bootstraps the same stack
# natively: the pre-installed PostgreSQL 16 cluster, a Python 3.12 venv with
# backend/requirements.txt, and the frontend's npm dependencies.
#
# Not covered natively: Keycloak (OIDC login). Use `manage.py createsuperuser`
# plus Django admin / the session login when a signed-in user is needed.
#
# Idempotent: safe to re-run; the container image is cached after it finishes.
set -euo pipefail

# Local dev setup only — on a developer machine `docker compose up -d` stays
# the documented path (see README.md).
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
cd "$ROOT"

log() { echo "[session-start] $*"; }

# --- PostgreSQL 16 -----------------------------------------------------------
# The port shift to 5433 in docker-compose.yml only exists so Abstimmbar and
# Ausleihbar can run side by side; natively the default 5432 is free.
log "starting PostgreSQL"
service postgresql start >/dev/null 2>&1 || true
for _ in $(seq 1 30); do
  pg_isready -q && break
  sleep 1
done
pg_isready || { echo "[session-start] PostgreSQL did not come up" >&2; exit 1; }

log "ensuring role + database 'abstimmbar'"
su postgres -c "psql -tAc \"SELECT 1 FROM pg_roles WHERE rolname='abstimmbar'\"" | grep -q 1 \
  || su postgres -c "psql -qc \"CREATE ROLE abstimmbar LOGIN PASSWORD 'abstimmbar' CREATEDB SUPERUSER\"" >/dev/null
su postgres -c "psql -tAc \"SELECT 1 FROM pg_database WHERE datname='abstimmbar'\"" | grep -q 1 \
  || su postgres -c "createdb -O abstimmbar abstimmbar"

# --- Backend -----------------------------------------------------------------
# Python 3.12 as in the Dockerfile (the sandbox default python3 is older).
if [ ! -x .venv/bin/python ]; then
  log "creating .venv (python3.12)"
  python3.12 -m venv .venv
  .venv/bin/pip install --quiet --upgrade pip
fi

# requirements.txt pulls the shared basicbar-* packages from the UOS GitLab;
# hash the file so a dependency bump reinstalls on the next session.
REQ_STAMP=".venv/.requirements.sha256"
REQ_HASH="$(sha256sum backend/requirements.txt | cut -d' ' -f1)"
if [ "$(cat "$REQ_STAMP" 2>/dev/null || true)" != "$REQ_HASH" ]; then
  log "installing backend requirements"
  .venv/bin/pip install --quiet -r backend/requirements.txt
  # ruff is the CI linter (.gitlab-ci.yml), not a runtime dependency.
  .venv/bin/pip install --quiet ruff
  echo "$REQ_HASH" > "$REQ_STAMP"
else
  log "backend requirements up to date"
fi

log "applying migrations"
(cd backend && POSTGRES_HOST=127.0.0.1 "$ROOT/.venv/bin/python" manage.py migrate --noinput >/dev/null)

log "compiling gettext catalogs"
# The framework-free participant page uses Django gettext; .mo files are not
# in git, so the German page would fall back to English without this.
# (Note: the catalog is cached in-process — restart the server after editing .po.)
command -v msgfmt >/dev/null 2>&1 || {
  log "installing gettext"
  apt-get install -y -qq gettext >/dev/null 2>&1 \
    || { apt-get update -qq >/dev/null 2>&1 && apt-get install -y -qq gettext >/dev/null 2>&1; } \
    || log "could not install gettext"
}
if command -v msgfmt >/dev/null 2>&1; then
  (cd backend && "$ROOT/.venv/bin/python" manage.py compilemessages >/dev/null 2>&1) || \
    log "compilemessages failed (non-fatal)"
else
  log "msgfmt missing — skipping compilemessages"
fi

# --- Frontend ----------------------------------------------------------------
# npm install (not ci) so the cached container image can be reused.
log "installing frontend dependencies"
(cd frontend && npm install --no-audit --no-fund >/dev/null)

# --- Session environment -----------------------------------------------------
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  {
    echo "export PATH=\"$ROOT/.venv/bin:\$PATH\""
    # 'localhost' would resolve to ::1 first; pin the cluster explicitly.
    echo 'export POSTGRES_HOST=127.0.0.1'
    echo 'export POSTGRES_PORT=5432'
    echo 'export DJANGO_DEBUG=1'
  } >> "$CLAUDE_ENV_FILE"
fi

log "ready — backend: python backend/manage.py …, frontend: npm run dev (in frontend/)"
