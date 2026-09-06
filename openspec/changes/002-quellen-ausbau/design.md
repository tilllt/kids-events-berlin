# Design — Change 002 Quellen-Ausbau

## Vorgehen je Quelle (deterministisch, kein LLM)

1. **Live-Erkundung** (einmalig, im Dev-Loop): robots.txt, Struktur der Listing-/Detail-Seiten, URL-Muster, Pagination/AJAX, JSON-LD-Vorkommen. Befunde dokumentieren in `docs/quellen.md` und als Adapter-Kommentar.
2. **Fixtures:** echte HTML-Proben (Listing + 1–2 Detailseiten, repräsentativ inkl. Kinder-/Familien-Event) unter `tests/fixtures/<quelle>/`, versioniert.
3. **Adapter** `app/adapters/<quelle>.py`: Parser gegen Fixtures (offline testbar), Extraktion nach Spec-Req 2 (JSON-LD → hEvent → CSS → Regex).
4. **Registry** in `app/adapters/__init__.py` + Mengenbereich je Quelle.
5. **Tests:** Fixture-Parser-Tests + Idempotenz via bestehendem Pipeline-Offline-Testmuster; CI-grün.
6. **Online-Gegenprobe:** ein echter Lauf je Quelle (> 0 Events, zweiter Lauf `n_neu=0`), nur lokal/Dev, nicht im Container-Scheduler-Zyklus.

## Quellen-Matrix (Ziel)

| Quelle | CMS/Struktur | Extraktionspfad | Kinder-Filter | Menge (erwartet) |
|---|---|---|---|---|
| jup.berlin/events | Drupal 10, Server-HTML | CSS (Artikel) | Bezirk/Kategorien-Filter | vorhanden (MVP) |
| berlinmitkind.de | WordPress + Events Manager | JSON-LD (Detail), CSS/AJAX (Liste) | redaktionell: Titel/Beschreibung-Regeln | 5–60 |
| zlb.de | TYPO3, Server-HTML | CSS (Artikel), Datum-Muster | Regel-Lexikon (Kinder/Familie) | 5–80 |
| familienportal.berlin.de | offen (Live-Befund) | nach Befund | Kategorien/Familie | 5–50 |

## Risiken & Gegenmaßnahmen

- **AJAX-Listing (berlinmitkind):** Falls Liste nur per AJAX lädt → dokumentierten Endpunkt direkt fetchen (deterministisch); sonst Server-HTML-Listenansicht nutzen.
- **TYPO3-Selektoren fragil (ZLB):** Fixture-Test schlägt bei Umbau an; Struktur-Hash/Anomalie-Alarm greift (Spec-Req 3).
- **familienportal Fetch-Fehler:** ggf. TLS/UA-Problem → mit Browser-UA + Retry testen; wenn Seite weiter nicht erreichbar: Quelle auf „blockiert/pending“ setzen, nicht erfinden.
- **Duplikate zu jup:** kinderkulturkalender nicht aufnehmen (gleiche DB); sonst greift Merge mit Provenienz, keine blinden Überschreibungen.
