# ImmichChrono

Findet und korrigiert falsche Aufnahmedaten in einer Immich-Bibliothek (FastAPI-Backend + SvelteKit-UI, ein Docker-Image). Texte, README, CHANGELOG auf Deutsch.

## Layout
- `backend/immichchrono/`: `api.py` (Routen), `main.py`, `config.py` (Settings aus Env, beim Import gelesen), `immich.py` (Immich-Client), `db.py` (SQLite), `scanner.py`, `suggestions.py` (speichern/anwenden/rückgängig), `camera_shift.py`, `trim.py`, `claude.py`/`ollama.py` (optionale Bildanalyse)
- `backend/immichchrono/detectors/`: Heuristiken (`filename`, `exifdeep`, `folder`, `context`, `ocr`, `suspects`), `combine.py` führt sie zusammen
- `backend/tests/`: `test_api.py`, `test_detectors.py`; `conftest.py` setzt Env (`DATA_DIR` tmp, `IMMICH_URL=http://immich.test`) vor dem Import
- `web/src/routes/` (Seiten), `web/src/lib/` (`api.ts`, `format.ts`, `state.svelte.ts`, `components/`); Svelte 5 (Runes) + `@immich/ui`, adapter-static

## Befehle
- Backend (in `backend/`, venv: `python3.13 -m venv .venv && .venv/bin/pip install -e '.[dev]'`): `.venv/bin/ruff check .` · `.venv/bin/pytest -q [-k filter]`
- Web (in `web/`): `pnpm lint` · `pnpm typecheck` · `pnpm test` · `pnpm build` (wie CI-Job `web`)
- Dev: `IMMICH_URL=… DATA_DIR=.devdata .venv/bin/uvicorn immichchrono.main:app --reload`, parallel `pnpm dev` (Proxy auf :8000)
- Während der Arbeit nur betroffenen Teil testen; backend und web sind unabhängig, vollen Lauf vor dem Commit.

## Fallen
- Tests nie gegen echtes Immich/Claude/Ollama: Fakes bzw. httpx-Mock, `ANTHROPIC_API_KEY`/`OLLAMA_URL` bleiben in Tests ungesetzt.
- `web/build` wird im Dockerfile nach `/app/static` kopiert (`STATIC_DIR`); `backend/immichchrono/static` existiert im Repo nicht. `web/build`, `.venv`, `.devdata` sind gitignored.
- Änderungen schreiben echte Aufnahmedaten in Immich: Anwenden immer mit gespeichertem `previous_date` (Rückgängig), Auto-Übernahme nur für sehr sichere Vorschläge.
- Neue Detektoren: Zeitzonen/Sommerzeit und Randfälle in `test_detectors.py` abdecken (`DEFAULT_TZ`, Standard `Europe/Berlin`).
- Beispiel-Hosts nur reservierte (`immich.test`, `example.com`).

## Plan/Stand
- Kein `docs/`: `README.md` (Ablauf, Env-Variablen, Entwicklung) und `CHANGELOG.md` (Format `## [X.Y.Z] – Datum`).

## Release
- Version in `backend/pyproject.toml` und `web/package.json` plus neuer CHANGELOG-Eintrag `## [X.Y.Z]`; dann Tag `vX.Y.Z`.
- `release.yml` baut das Image nativ amd64/arm64 nach `ghcr.io/minifyx/immichchrono` und legt das GitHub-Release aus dem CHANGELOG-Abschnitt an (keine Desktop-/Mobile-Artefakte).

## Security
- Kritisch: `backend/immichchrono/auth.py` (Login/Sessions, `SESSION_SECRET`, Cookies), `immich.py` (Zugriff mit Nutzer-Token), `claude.py` (API-Key, Kostenbudget), Schreibpfad in `suggestions.py`.
- Vor jedem Feature-Release den globalen Subagent `security-reviewer` über den Bereich seit dem letzten Tag laufen lassen; Ergebnis nach `docs/security-review-<version>.md`.
