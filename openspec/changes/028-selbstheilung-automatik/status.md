# Change 028 — Selbstheilung: Knopf + Automatik mit Meldung (ausgeliefert 2026-10-16)

Status: **ausgeliefert und live belegt**. Auftrag des Nutzers (16.10.2026):
„Baue den Knopf ein, aber etabliere auch einen automatischen Modus, der versucht
zu reparieren, oder wenn das nicht klappt, Bescheid sagt."

## Was live läuft

- Commits `8ba2183`, `…` (zweiter und dritter Deploy siehe unten), ausgeliefert
  über `bash /opt/data/coolify_deploy_kinderkram.sh` → `END=finished`,
  `running:healthy`, Container
  `fk4ecovtzmyx2vbwbmlfblx4-085413913510`.
- Im **ausgelieferten Abbild** geprüft: `_sh.lauf_auswerten(` in
  `app/pipeline.py:354`, `store.heilung_anlegen`, 13 × „heilung" in `admin.html`.
- Neue Endpunkte live: `GET /api/admin/heilungen` (Fälle + geltende
  Einstellungen + `llm_bereit`), `GET /api/admin/heilungen/verlauf`,
  `GET /api/admin/heilungen/{id}`, `POST …/{id}/uebernehmen|ablehnen|zuruecknehmen`,
  `POST /api/admin/sources/{quelle}/reparieren` (Knopf).
- Oberfläche live geprüft (`curl https://kinderkram.cia-spandau.de/admin`): alle
  14 neuen IDs vorhanden, Bereich „Selbstheilung" **offen** ausgeliefert,
  `admin.js` enthält den Knopf und die Endpunkte.

## Betriebs-Vorbedingung, die gefehlt hat (wichtig)

Die App hatte **keinen LLM-Endpunkt**: `settings` enthielt kein `llm_*`, und der
Vorgabewert im Repo ist seit dem Redaktions-Commit `7f02bf3` der Platzhalter
`<LLM_BASE_URL>` — nicht leer, aber keine Adresse. Ohne Endpunkt kann die
Automatik nur melden. Jetzt gesetzt (per Admin-API):

    llm_base_url = http://192.168.178.140:8088/v1      (KI-Box, LAN-Weg von .50)

Belegt mit `POST /api/admin/llm/test`: `ok`, 1,58 s, Modell
`llamacpp-gemma4-12B-unsloth`. `GET /api/admin/heilungen` → `llm_bereit: true`.
Der Platzhalter zählt bewusst **nicht** als eingerichtet (`selbstheilung.llm_bereit`).

## Live-Nachweise (16.10.2026)

1. **Erstbefund (Altlast) unverändert:** `heilungen` enthält weiterhin die Zeile
   vom 22.09.2026 (`museumsportal`, `verdacht`, `beobachtet`) — die Erkennung von
   damals war korrekt, es gab nur keinen Weg zur Reparatur.
2. **Knopf, Fall 2 (10:57):** `familienportal`, Befund `selektoren_tot`, Modell
   antwortete ohne verwertbares YAML → Status `offen`, Meldung „das Modell
   lieferte keine brauchbaren Regeln. Es wurde nichts geändert.", Regeln
   byteidentisch, E-Mail raus (`benachrichtigt_am` gesetzt).
3. **Knopf, Fall 3 (11:05):** dasselbe, diesmal mit gültigem YAML — das Modell
   ließ die Regeln unverändert; das **Gate** lehnte ab:
   „Probelauf heute: 0 Treffer, gefordert 5" → Status `verworfen`, Regeln
   unverändert, Meldung ausdrücklich „Reparaturvorschlag DURCHGEFALLEN … Die
   Regeln sind unverändert.", E-Mail raus.
4. **Knopf, Fall 4 (11:11, nach dem zweiten Deploy):** Status `unreparierbar`
   mit der präzisen Meldung „Die Seite liefert keinen einzigen Termin-Eintrag mit
   Datum (die Liste entsteht vermutlich erst im Browser) — ein Selektorwechsel
   kann das nicht beheben, die Quelle braucht einen neuen Weg." Kein
   Modell-Aufruf, kein Kontingentverbrauch, Regeln unverändert, E-Mail raus.

`regel_historie` ist leer — es wurde in keinem Fall eine Regel geändert.

## Ursache des Falls `familienportal` — gefunden und behoben (16.10.2026)

Am 14.10. lieferte die Quelle 2.671 Termine, am 15. und 16.10. **null**, in allen
Läufen `n_fehler = 0`. Die Seite antwortete mit 200, 45.914 Zeichen, enthielt
aber keinen einzigen Termin-Block.

**Ursache:** Das Portal hat am **14.10.2026** eine neue Fassung ausgeliefert
(Asset-Zeitstempel `?1791979895` ≈ 14.10.2026) und dabei die Art-Facette
„Kinder & Jugendliche" (`filter_19[]=KinderJugendliche`) entwertet. Gemessen am
16.10.2026 im 21-Tage-Fenster: mit der Facette meldet die Seite selbst
„**0 Veranstaltungen**", ohne sie „**1355 Veranstaltungen**". Die Werte `Kinder`
und `Jugendliche` kennt das Portal nicht — unbekannte Werte ignoriert es
stillschweigend, die Antwort ist dann ungefiltert (deshalb sahen sie brauchbar
aus). Kein JavaScript-Problem: der echte Browser zeigt dieselbe leere Seite.

**Behoben** (Commit mit `FAMILIENPORTAL_REGELN`): Abfrage nur noch mit dem
Zeitraum-Filter, Art-Facette entfernt, Begründung als Kommentar in den Regeln.
Regeln per `PUT /api/admin/sources/familienportal/regeln` live ausgerollt
(die Regeln im Betrieb sind eine Kopie der Code-Vorgabe).

**Nachweis (live, 16.10.2026 11:34–11:39 MESZ):** Lauf `status=ok`,
`n_events=2743` in 5m26s, danach **771 Termine** im Bestand (50 heute, 57
morgen, 664 nach dem 18.10. — die Voraus-Tiefe ist zurück), Stichproben sind
Kinder-/Familientermine.

**Nebenbei verbessert:** `diagnose()` liest die Trefferzahl der Seite
(`treffer_laut_seite`). Meldet eine Seite selbst 0, steht das in jeder Meldung
(„die Seite meldet selbst „0 Veranstaltungen" für diese Abfrage"), und das
Modell bekommt den Hinweis, die **Listing-URL** zu prüfen statt die Selektoren —
der Selektor war hier nie das Problem.

**Offen:** Bei 1355 Veranstaltungen im Fenster (136 Seiten) dauert ein Lauf
~5,5 min; kein Erwachsenen-Filter mehr (das Portal ist der Familienkalender, die
12 leeren Art-Werte zeigen: Sensibeles wie Senioren/Frauen/Politik ist im
Fenster nicht belegt). Beobachten, ob der Bestand „kippt"; ggf. Whitelist der 10
belegten Art-Werte als Abfrage nachziehen.

## Tests

`tests/test_selbstheilung_auto.py` (26 Fälle) plus die bestehenden Suiten: 49–50
grün in `tests/test_selbstheilung*`, `test_admin_ui`, `test_pipeline_offline`.
Der **Gate** ist weiterhin nicht als Ganzes benutzbar: 12 rote Tests in
`tests/test_recherche_*` / `test_schul_import` sind Altlast aus dem
Redaktions-Commit `7f02bf3` (dieselbe Liste im `git worktree` auf `HEAD`, ohne
die eigenen Änderungen). Deshalb die belegte Route: committen, `git push`,
`bash /opt/data/coolify_deploy_kinderkram.sh`, `END=finished`, Zustand und
Live-Messung prüfen.

## Lehren, die im Skill stehen

- Ein Platzhalter ist kein Endpunkt — „nicht leer" ist keine Prüfung.
- Eine Seite **ohne jeden** Inhaltseintrag ist nicht per Selektor reparierbar;
  das gehört in die Meldung, statt Modell-Kontingent zu verbrennen.
- Eine unbrauchbare Modell-Antwort gehört mit Rohtext in die Fallakte
  (`beleg.modell_antwort`), sonst ist der Fehlschlag nicht nachvollziehbar.
- `heilungen_liste` liefert die Rohspalten (`beleg_json` als String) — Tests
  dürfen nicht `h["beleg"]` erwarten; die API parst erst.
