"""iCal-Ausgabe (RFC 5545) für gefilterte Terminlisten — Change 018.

Warum ohne Bibliothek: iCal ist reiner Text, und wir brauchen nur VEVENT mit
lokaler Zeit. Eine Abhängigkeit wäre hier mehr Risiko als Nutzen.

Zwei Dinge, die man leicht falsch macht und die hier bewusst richtig sind:
- **Lokale Zeit mit TZID=Europe/Berlin** plus VTIMEZONE-Block. Als UTC
  geschrieben würden Termine in Clients ohne Zeitzonentabelle verrutschen.
- **Stabile UID je Termin** (Kennung aus Quelle und Quell-ID). Ändert sich die
  UID, legt jeder Kalender bei jeder Aktualisierung eine Dublette an.
"""
from __future__ import annotations

from datetime import datetime, timedelta

PRODID = "-//kinderkram//kinderkram.cia-spandau.de//DE"
DOMAIN = "kinderkram.cia-spandau.de"

# Zeitzonenblock für Europe/Berlin (Sommer-/Winterzeit nach EU-Regel seit 1996).
VTIMEZONE = """BEGIN:VTIMEZONE
TZID:Europe/Berlin
BEGIN:DAYLIGHT
TZOFFSETFROM:+0100
TZOFFSETTO:+0200
TZNAME:CEST
DTSTART:19700329T020000
RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU
END:DAYLIGHT
BEGIN:STANDARD
TZOFFSETFROM:+0200
TZOFFSETTO:+0100
TZNAME:CET
DTSTART:19701025T030000
RRULE:FREQ=YEARLY;BYMONTH=10;BYDAY=-1SU
END:STANDARD
END:VTIMEZONE"""


def _text(wert) -> str:
    """iCal-Text escapen (RFC 5545, 3.3.11)."""
    s = str(wert or "")
    s = s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
    s = s.replace("\r\n", "\\n").replace("\n", "\\n").replace("\r", "\\n")
    return s


def _falten(zeile: str, breite: int = 73) -> str:
    """Zeilen auf 75 Oktette falten — sonst brechen manche Clients mitten im Feld.

    Gefaltet wird an Zeichengrenzen; Umlaute zählen zwei Oktette, deshalb eine
    Sicherheitsbreite von 73.
    """
    if len(zeile.encode("utf-8")) <= 75:
        return zeile
    teile, aktuell = [], ""
    for zeichen in zeile:
        if len((aktuell + zeichen).encode("utf-8")) > breite:
            teile.append(aktuell)
            aktuell = zeichen
        else:
            aktuell += zeichen
    teile.append(aktuell)
    return "\r\n ".join(teile)


def _lokal(wert: str | None) -> datetime | None:
    if not wert:
        return None
    try:
        return datetime.fromisoformat(wert)
    except ValueError:
        return None


def _stamp(dt: datetime, ganztags: bool) -> str:
    return dt.strftime("%Y%m%d") if ganztags else dt.strftime("%Y%m%dT%H%M%S")


def _zeile(name: str, wert: str, *, param: str = "") -> str:
    return _falten(f"{name}{param}:{wert}")


def vevent(ev: dict, *, entfernung_km: float | None = None,
           stand: str = "") -> list[str]:
    """Ein VEVENT als Zeilenliste."""
    start = _lokal(ev.get("start_local")) or _lokal(ev.get("start_iso"))
    if start is None:
        return []
    ganztags = bool(ev.get("ganztags"))
    ende = _lokal(ev.get("ende_local"))
    if ende is None:
        ende = start + (timedelta(days=1) if ganztags else timedelta(hours=2))

    uid = f"{ev.get('id') or 'ev'}@{DOMAIN}"
    dtstamp = _lokal(ev.get("geholt_am")) or datetime.utcnow()

    beschreibung = [ev.get("beschreibung_kurz") or ""]
    if entfernung_km is not None:
        beschreibung.append(f"Entfernung: {entfernung_km:.1f} km Luftlinie")
    if stand:
        beschreibung.append(f"Stand der Daten: {stand}")
    if ev.get("source_url"):
        beschreibung.append(f"Quelle: {ev['source_url']}")
    beschreibung.append("Veranstaltungskalender kinderkram.cia-spandau.de")

    orte = " · ".join(x for x in (ev.get("ort"), ev.get("adresse")) if x)
    zeilen = ["BEGIN:VEVENT",
              _zeile("UID", uid),
              f"DTSTAMP:{dtstamp.strftime('%Y%m%dT%H%M%SZ')}"]
    if ganztags:
        zeilen.append(f"DTSTART;VALUE=DATE:{_stamp(start, True)}")
        zeilen.append(f"DTEND;VALUE=DATE:{_stamp(ende + timedelta(days=1), True)}")
    else:
        zeilen.append(f"DTSTART;TZID=Europe/Berlin:{_stamp(start, False)}")
        zeilen.append(f"DTEND;TZID=Europe/Berlin:{_stamp(ende, False)}")
    zeilen.append(_zeile("SUMMARY", _text(ev.get("titel"))))
    if orte:
        zeilen.append(_zeile("LOCATION", _text(orte)))
    zeilen.append(_zeile("DESCRIPTION", _text("\n".join(x for x in beschreibung if x))))
    if ev.get("source_url"):
        zeilen.append(_zeile("URL", _text(ev["source_url"])))
    if ev.get("kategorien"):
        kat = ev["kategorien"]
        kat = ", ".join(kat) if isinstance(kat, list) else str(kat)
        zeilen.append(_zeile("CATEGORIES", _text(kat)))
    zeilen.append("END:VEVENT")
    return zeilen


def kalender(events: list[dict], *, name: str = "kinderkram",
             stand: str = "", entfernungen: dict | None = None) -> str:
    """Vollständiger iCal-Text."""
    zeilen = ["BEGIN:VCALENDAR",
              "VERSION:2.0",
              _zeile("PRODID", PRODID),
              "CALSCALE:GREGORIAN",
              "METHOD:PUBLISH",
              _zeile("X-WR-CALNAME", _text(name)),
              "X-WR-TIMEZONE:Europe/Berlin"]
    zeilen.append(VTIMEZONE)
    for ev in events:
        entf = (entfernungen or {}).get(ev.get("id"))
        zeilen.extend(vevent(ev, entfernung_km=entf, stand=stand))
    zeilen.append("END:VCALENDAR")
    text = "\r\n".join(zeilen) + "\r\n"
    # RFC 5545 verlangt CRLF. Innere Zeilenumbrüche (z. B. im VTIMEZONE-Block)
    # brachten sonst 16 Zeilen mit nur LF in die Datei — manche Kalenderclients
    # stolpern darüber.
    return text.replace("\r\n", "\n").replace("\n", "\r\n")
