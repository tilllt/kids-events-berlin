# Change 013 — E-Mail-Versand und -Empfang für die Schul-Anfragen

**Status:** gebaut, getestet, deployt und gegen das echte Postfach verifiziert
(2026-09-13). Postfach: **kinderkram@mekotools.de** über w00d77ee.kasserver.com
(Provider KAS).

## Why

Die Stufe nach der Recherche: Schulen, deren Tag der offenen Tür weder auf der
eigenen Website noch über die Websuche zu finden war, werden per Mail gefragt —
und die Antworten landen wieder im Tool. Dafür braucht die App ein eigenes
Postfach (Absender und Reply-To sind dieselbe Adresse, damit Antworten sicher
zurückkommen).

## Umsetzung

- `app/mail.py` (Standardbibliothek, kein Fremddienst): SMTP über SSL (465) oder
  STARTTLS (587), IMAP über SSL (993), Login-Test, Versand, Abruf ungelesener
  Nachrichten inkl. MIME-Kopfzeilen-Dekodierung und HTML-Only-Fallback.
- **Eine Vokabel:** die internen Namen werden aus den vorhandenen
  `smtp_*`/`imap_*`/`mail_*`-Einstellungen abgebildet, damit die Werte im Admin
  sichtbar bleiben und der bestehende Schul-Versandweg unverändert weiterläuft.
- **Getrennte Zeilen in der GUI** (User-Vorgabe): Absenderadresse, Postfach-
  Passwort, SMTP-Server/-Port/-Verschlüsselung, IMAP-Server/-Port, **Reply-To**,
  **Betreff**, **Nachricht** — alle mit Standardwerten vorgefüllt, Reply-To
  `kinderkram@mekotools.de`. Leere Felder werden in der Antwort mit dem Standard
  angezeigt (Kennzeichnung `…_ist_default`).
- **Geheimnisse verlassen den Server nicht:** `GET`/`PUT /settings` liefern
  `smtp_pass`, `llm_api_key` und `brave_api_key` nur noch als `…_gesetzt`-Marker.
  (Vorher ging der Brave-Key im Klartext in die Antwort — mitbehoben.)
- **Versand-Protokoll + Bremse** (`mail_versand`): jeder Versuch wird vor dem
  Senden verbucht, Grenzen 40/Tag und 20/Stunde. Verhindert, dass ein Fehllauf
  700 Schulen anschreibt; erreichte Grenze = sichtbarer Klartext.
- Neue Endpunkte: `GET /api/admin/mail` (Zustand ohne Passwort),
  `POST /api/admin/mail/test` (SMTP+IMAP-Login), `POST /api/admin/mail/testmail`
  (echte Testmail), `POST /api/admin/mail/abrufen` (ungelesene Antworten).

## Verifiziert (produktiv)

- `GET /api/admin/mail`: Adresse und Reply-To `kinderkram@mekotools.de`,
  `fehlende_angaben: []`, Versandzähler 0, keine Bremse aktiv.
- `POST /mail/test`: SMTP-Login OK (w00d77ee.kasserver.com:465), IMAP-Login OK,
  6 Ordner.
- `POST /mail/testmail`: echte Testmail gesendet (`ok: true`), Protokoll
  `heute: 1, diese_stunde: 1, fehler_gesamt: 0`.
- `POST /mail/abrufen`: 1 ungelesene Nachricht gelesen (Brave-Rechnung vom
  13.09.2026) — der Leseweg steht.
- Passwort erscheint in keiner API-Antwort (`smtp_pass: ""`,
  `smtp_pass_gesetzt: true`).
- Tests: **233 grün** (10 neu).

## Zusätzlich eingerichtet

- **himalaya v2.1.0** im Agent-Container (`~/.local/bin/himalaya`), Konto
  `kinderkram` mit IMAP+SMTP konfiguriert; Passwort über `password.command`
  (`/opt/data/bin/mail_pass.sh`), nicht im Klartext in der Konfigurationsdatei.
  `himalaya account check` → imap OK, smtp OK. Testmail an <REDACTED>
  gesendet (SMTP bestätigt „Message successfully sent").

## Offen

1. **Antwortverarbeitung (Text → Termin):** der Abruf liefert die Mails, die
   automatische Auswertung der Antworten (LLM-Extraktion mit derselben
   Belegprüfung, Zuordnung Schule ↔ Absender) fehlt noch.
2. **Versand an Schulen** ist scharf (mail_aktiv = 1), aber noch nicht für eine
   größere Menge ausgelöst — bewusst: erst nach Freigabe durch den Nutzer.
3. Brave-Websuche läuft mit Schlüssel; Messung der zusätzlichen Treffer steht aus.
