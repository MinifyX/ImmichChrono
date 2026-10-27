# ImmichChrono

Findet Fotos und Videos mit falschem Datum in deiner [Immich](https://immich.app)-Bibliothek, schlägt das richtige Datum vor und korrigiert es über die Immich-API – mit Prüfansicht im Look der Immich-Weboberfläche.

## Was erkannt wird

| Problem | Beispiele | Woher der Vorschlag kommt |
| --- | --- | --- |
| **Fehlendes Datum** | WhatsApp-/Messenger-Bilder, Screenshots, Downloads | Dateiname (`IMG-20190714-WA0003.jpg`, `Screenshot_2021-03-02-…`), Nachbarn im Album, Duplikate |
| **Falsche Kamera-Uhr** | Zweitkamera nach Batteriewechsel auf 2000/2015, Zeitzone vergessen | GPS-Zeit, Vergleich mit gleichzeitig aufgenommenen Handyfotos, Offset pro Kamera |
| **Scans** | Abgescannte Papierfotos mit Scan-Datum | Datumsaufdruck per Immich-OCR, Album-/Ordnernamen, Ollama oder Claude (Bildinhalt) |
| **Unplausibles** | Datum in der Zukunft, vor 1900, Upload ≫ Aufnahme | Kombination aller Quellen |

Zusätzlich gibt es einen **Analysebericht** (Übersicht) mit Kategorien, Problemarten und offenen Vorschlägen pro Quelle.

## Ablauf

1. **Scan** – liest alle Assets über die Immich-API (inkrementell; „Vollständiger Scan“ liest alles neu).
2. **Heuristiken** – Dateinamen, Ordner- und Albumnamen, Immich-OCR-Text, tiefe Metadaten per exiftool (GPS-Zeit, XMP/IPTC/QuickTime), Duplikate, Album-Nachbarn, Kamera-Offsets.
3. **Ollama (optional)** – lokale Bildanalyse für Fälle ohne Hinweise, mit einstellbarem Maximum pro Lauf.
4. **Claude (optional)** – nur auf Knopfdruck für ausgewählte Bilder, mit Kostenschätzung vorab und Budgetgrenze pro Lauf.
5. **Prüfen** – Vorschläge filtern, übernehmen, ablehnen oder manuell setzen. Jede Änderung steht im **Verlauf** und lässt sich rückgängig machen.

**Automatisch übernommen** werden nur sehr sichere Fälle (GPS-Zeit, eindeutiger Dateiname, exaktes Duplikat) – abschaltbar in den Einstellungen.

## Installation

ImmichChrono läuft als eigener Container im selben Docker-Netzwerk wie `immich-server`. Angemeldet wird mit dem normalen Immich-Login; ImmichChrono speichert kein Passwort, nur das Immich-Session-Token.

```yaml
# in die docker-compose.yml von Immich übernehmen
  immichchrono:
    container_name: immichchrono
    image: ghcr.io/minifyx/immichchrono:latest
    restart: unless-stopped
    ports:
      - "2284:8000"
    environment:
      IMMICH_URL: http://immich-server:2283
      IMMICH_PUBLIC_URL: https://photos.example.com
      TZ: Europe/Berlin
    volumes:
      - immichchrono-data:/data

volumes:
  immichchrono-data:
```

Danach `http://<server>:2284` öffnen. Alternativ liegt eine fertige [`compose.yaml`](compose.yaml) im Repo:

```bash
docker compose -f docker-compose.yml -f /pfad/zu/ImmichChrono/compose.yaml up -d
```

### Umgebungsvariablen

| Variable | Standard | Beschreibung |
| --- | --- | --- |
| `IMMICH_URL` | `http://immich-server:2283` | Interne Adresse des Immich-Servers |
| `IMMICH_PUBLIC_URL` | – | Adresse für „In Immich öffnen“-Links |
| `TZ` / `DEFAULT_TZ` | `Europe/Berlin` | Zeitzone für Dateinamen ohne Zonenangabe |
| `ANTHROPIC_API_KEY` | – | Aktiviert die Claude-Analyse |
| `CLAUDE_MODEL` | `claude-opus-5-5` | Standardmodell (in den Einstellungen änderbar) |
| `OLLAMA_URL` | – | z. B. `http://ollama:11434` |
| `OLLAMA_MODEL` | `llava:7b` | Vision-Modell für Ollama |
| `COOKIE_SECURE` | `false` | Hinter HTTPS auf `true` setzen (wird bei erkanntem HTTPS automatisch gesetzt) |
| `FORWARDED_ALLOW_IPS` | `127.0.0.1` | IP oder Subnetz des Reverse-Proxys, z. B. `172.18.0.0/16` |
| `SESSION_TTL_HOURS` | `720` | Gültigkeit der Anmeldung (wird alle 10 Minuten bei Immich gegengeprüft) |
| `DATA_DIR` | `/data` | SQLite-Datenbank und Cache |

## Datenschutz und Kosten

- Heuristiken und Ollama laufen vollständig lokal.
- An Claude gehen nur die Bilder, die du ausdrücklich auswählst – als verkleinerte Vorschau plus Metadaten (Dateiname, Album, Kamera). Vor dem Start siehst du die geschätzten Kosten; das Budget pro Lauf wird hart eingehalten.
- Änderungen an Immich passieren ausschließlich über `PUT /api/assets/{id}` (Feld `dateTimeOriginal`). Die Originaldateien bleiben unverändert.

## Entwicklung

```bash
# Backend
cd backend && python3.13 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/pytest -q && .venv/bin/ruff check .
IMMICH_URL=http://localhost:2283 DATA_DIR=.devdata .venv/bin/uvicorn immichchrono.main:app --reload

# Frontend (Proxy auf :8000)
cd web && pnpm install && pnpm dev
pnpm lint && pnpm typecheck && pnpm test && pnpm build
```

Ein Release entsteht durch einen Tag `vX.Y.Z`: Die Pipeline baut das Image nativ für amd64 und arm64, veröffentlicht es auf `ghcr.io/minifyx/immichchrono` und legt ein GitHub-Release mit dem CHANGELOG-Eintrag an.
