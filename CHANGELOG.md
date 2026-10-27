# Changelog

## [0.1.1] – 2026-10-27

- **Entscheidungsprotokoll:** Beim Übernehmen, Ablehnen, manuellen Setzen und Zurücknehmen lässt sich ein Grund wählen (z. B. „Richtiges Jahr, falscher Tag“, „Datum ist Scan-/Download-/Weiterleitungsdatum“) plus freier Text. Jede Entscheidung wird mit einer Momentaufnahme gespeichert (Quelle, Sicherheit, alter/neuer Wert, Abstand in Tagen, Dateinamen-Muster, Kamera, Problemarten, GPS, Claude-Modell).
- Frühere Entscheidungen werden beim Start mit Grund „unbekannt“ übernommen.
- Neue Seite **Auswertung**: Übernahmequote je Quelle, Kamera, Problemart und Dateinamen-Muster sowie Häufigkeit der Gründe.
- Export als JSON Lines: Knopf auf der Auswertungsseite, `GET /api/decisions/export` oder `docker exec immichchrono python -m immichchrono.export > entscheidungen.jsonl`.
- Ablehnen jetzt auch direkt im Detailfenster.

## [0.1.0] – 2026-10-27

Erste Version.

- Scan der Immich-Bibliothek mit Erkennung von fehlenden Daten, falschen Kamera-Uhren, Zeitzonenfehlern, Scans und unplausiblen Daten
- Heuristiken: Dateinamen, EXIF, GPS-Zeit, Duplikate, Album-Nachbarn, Kamera-Offsets
- Optionale Bildanalyse mit Ollama (lokal) und Claude (auf Knopfdruck, mit Kostenschätzung und Budget)
- Weboberfläche im Immich-Look: Übersicht/Bericht, Prüfen, Ungeklärt, Kamera-Uhr, Verlauf mit Rückgängig, Einstellungen
- Automatisches Übernehmen sehr sicherer Vorschläge (abschaltbar)
- Docker-Image für amd64 und arm64
