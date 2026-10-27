# Changelog

## [0.1.0] – 2026-10-27

Erste Version.

- Scan der Immich-Bibliothek mit Erkennung von fehlenden Daten, falschen Kamera-Uhren, Zeitzonenfehlern, Scans und unplausiblen Daten
- Heuristiken: Dateinamen, EXIF, GPS-Zeit, Duplikate, Album-Nachbarn, Kamera-Offsets
- Optionale Bildanalyse mit Ollama (lokal) und Claude (auf Knopfdruck, mit Kostenschätzung und Budget)
- Weboberfläche im Immich-Look: Übersicht/Bericht, Prüfen, Ungeklärt, Kamera-Uhr, Verlauf mit Rückgängig, Einstellungen
- Automatisches Übernehmen sehr sicherer Vorschläge (abschaltbar)
- Docker-Image für amd64 und arm64
