"""Change 008: überlappende Serien-Zwillinge einer Quelle zusammenfassen.

Realer Anlass: jup.berlin führt einen mehrtägigen Ferienworkshop als mehrere,
je um einen Tag verschobene Einträge derselben Spanne → 13 Karteileichen in
Liste und Karte. Echte Serientermine (berührende Slots) dürfen NICHT kollabieren.
"""
from datetime import datetime, timedelta

from app.model import TZ_BERLIN, make_event_id
from app.pipeline import scrape
from app.store import Store, titel_kern

QUELLE = "jup-berlin"


def _ev(quelle: str, titel: str, start: datetime, ende: datetime | None,
        ort: str = "MAXIM, Kinder- und Jugendkulturzentrum", *, manuell: int = 0,
        nummer: int = 0, ganztags: bool = False) -> dict:
    """Minimal-Event für den Store (Pflichtfelder + Zeitspalten beide Formen)."""
    occ = start.astimezone(TZ_BERLIN).strftime("%Y%m%dT%H%M")
    seid = f"{titel}#{occ}#{nummer}"
    return {
        "id": make_event_id(quelle, seid),
        "titel": titel,
        "beschreibung_kurz": None,
        "start_iso": start.astimezone(TZ_BERLIN).isoformat(),
        "ende_iso": ende.astimezone(TZ_BERLIN).isoformat() if ende else None,
        "start_local": start.astimezone(TZ_BERLIN).strftime("%Y-%m-%dT%H:%M:%S"),
        "ende_local": (ende.astimezone(TZ_BERLIN).strftime("%Y-%m-%dT%H:%M:%S")
                       if ende else None),
        "ganztags": ganztags,
        "ort": ort,
        "adresse": None,
        "bezirk": None,
        "lat": None,
        "lon": None,
        "kostenlos": None,
        "quelle": quelle,
        "source_event_id": seid,
        "source_url": f"https://jup.berlin/events/{nummer}",
        "geholt_am": datetime(2026, 9, 12, 12, 0, tzinfo=TZ_BERLIN).isoformat(),
        "manuell": manuell,
    }


def _d(tag: int, stunde: int, monat: int = 10) -> datetime:
    return datetime(2026, monat, tag, stunde, 0, tzinfo=TZ_BERLIN)


def test_ueberlappende_ketten_werden_auf_fruehesten_start_reduziert(tmp_path):
    store = Store(tmp_path / "events.db")
    titel = "Wie kommt das Milchhäuschen am Weißen See zu seinem Namen?"
    # 3 verschobene Kopien derselben Spanne (je 5 Tage, Start +1 Tag)
    for i in range(3):
        store.upsert_event(_ev(QUELLE, titel, _d(5 + i, 10), _d(9 + i, 16), nummer=i))

    entfernt = store.entferne_ueberlappende_zwillinge(QUELLE)
    assert len(entfernt) == 2, entfernt
    rest = [e for e in store.query_events({}) if e["titel"] == titel]
    assert len(rest) == 1
    # Der früheste Start (5.10. 10:00) bleibt — das ist der echte Termin.
    assert rest[0]["start_local"] == "2026-10-05T10:00:00"
    # Idempotent: zweiter Aufruf findet nichts mehr.
    assert store.entferne_ueberlappende_zwillinge(QUELLE) == []
    store.close()


def test_beruehrende_slots_sind_keine_dubletten(tmp_path):
    """ZLB-Stundenblöcke (09–10, 10–11 Uhr) dürfen NICHT zusammenfallen."""
    store = Store(tmp_path / "events.db")
    titel = "U-16 Wahllokal für Schulklassen"
    for i, (h1, h2) in enumerate([(9, 10), (10, 11), (11, 12)]):
        store.upsert_event(_ev(QUELLE, titel, _d(8, h1), _d(8, h2), nummer=i))
    assert store.entferne_ueberlappende_zwillinge(QUELLE) == []
    assert len([e for e in store.query_events({}) if e["titel"] == titel]) == 3
    store.close()


def test_verschiedene_orte_bleiben_getrennt(tmp_path):
    store = Store(tmp_path / "events.db")
    titel = "Keramikwerkstatt"
    store.upsert_event(_ev(QUELLE, titel, _d(5, 10), _d(9, 16), ort="Haus A", nummer=1))
    store.upsert_event(_ev(QUELLE, titel, _d(6, 10), _d(10, 16), ort="Haus B", nummer=2))
    assert store.entferne_ueberlappende_zwillinge(QUELLE) == []
    assert len([e for e in store.query_events({}) if e["titel"] == titel]) == 2
    store.close()


def test_manuell_gepflegte_events_bleiben(tmp_path):
    """Admin-Pflege gewinnt: manuell=1 wird nie als Dublette gelöscht."""
    store = Store(tmp_path / "events.db")
    titel = "Ferienworkshop (vom Admin korrigiert)"
    store.upsert_event(_ev(QUELLE, titel, _d(5, 10), _d(9, 16), nummer=1))
    store.upsert_event(_ev(QUELLE, titel, _d(6, 10), _d(10, 16), nummer=2, manuell=1))
    assert store.entferne_ueberlappende_zwillinge(QUELLE) == []
    assert len([e for e in store.query_events({}) if e["titel"] == titel]) == 2
    store.close()


def test_nur_die_gescrapte_quelle_wird_bereinigt(tmp_path):
    """Serien-Bereinigung wirkt nur auf die genannte Quelle.

    Change 011 ergänzt: die identische Veranstaltung aus einer ZWEITEN Quelle
    wird schon beim Schreiben zusammengeführt (jup-berlin hat Vorrang vor zlb),
    ihre Herkunft bleibt als Provenienz am Datensatz. `entferne_ueberlappende_
    zwillinge` rührt fremde Quellen weiterhin nicht an.
    """
    store = Store(tmp_path / "events.db")
    titel = "Doppelter Titel"
    store.upsert_event(_ev(QUELLE, titel, _d(5, 10), _d(9, 16), nummer=1))
    store.upsert_event(_ev(QUELLE, titel, _d(6, 10), _d(10, 16), nummer=2))
    store.upsert_event(_ev("zlb", titel, _d(5, 10), _d(9, 16), nummer=3))
    store.upsert_event(_ev("zlb", titel, _d(6, 10), _d(10, 16), nummer=4))

    # Quellenübergreifend zusammengeführt: keine zlb-Zeile mehr, aber Provenienz
    assert [e["quelle"] for e in store.query_events({})] == [QUELLE, QUELLE]
    for e in store.query_events({}):
        assert "zlb" in (e.get("quellen_json") or "")

    entfernt = store.entferne_ueberlappende_zwillinge(QUELLE)
    assert len(entfernt) == 1
    # Fremde Quelle hat nichts zu bereinigen — sie ist hier schon zusammengeführt
    assert store.entferne_ueberlappende_zwillinge("zlb") == []
    store.close()


def test_pipeline_raeumt_altlasten_und_meldet_sie(tmp_path, listing_p0, listing_p1,
                                                  detail_fam, detail_raetsel):
    """Offline-Lauf räumt vorhandene Kopien weg und meldet die Zahl."""
    store = Store(tmp_path / "events.db")
    store.seed_default_sources()
    titel = "Ferienworkshop mit überlappenden Quell-Einträgen"
    for i in range(3):
        store.upsert_event(_ev(QUELLE, titel, _d(5 + i, 10), _d(9 + i, 16), nummer=i))
    assert len([e for e in store.query_events({}) if e["titel"] == titel]) == 3

    jetzt = datetime(2026, 9, 4, 12, 0, tzinfo=TZ_BERLIN)
    summary = scrape(store, online=False,
                     listing_htmls=[listing_p0, listing_p1],
                     detail_html={"familiensportfest": detail_fam,
                                  "raetselabenteuer-berlin-prenzlauer-berg": detail_raetsel},
                     jetzt=jetzt)
    assert summary["n_fehler"] == 0
    assert summary["n_zwillinge_entfernt"] == 2, summary
    assert len([e for e in store.query_events({}) if e["titel"] == titel]) == 1
    # Regressionsschutz: echte Fixture-Events bleiben vollständig vorhanden.
    assert len([e for e in store.query_events({})
                if e["titel"] != titel]) >= 5
    store.close()


def test_laufendes_mehrtaegiges_event_ueberlebt_prune_stale(tmp_path):
    """Stale-Bereinigung richtet sich nach dem ENDE, nicht nach dem Start.

    Realer Befund 2026-09-12: der Ferienworkshop 09.–13.09. (Start 3+ Tage
    alt, läuft aber noch) wurde von der Start-Bedingung mitten im Lauf
    gelöscht — er verschwand aus Liste und Karte.
    """
    store = Store(tmp_path / "events.db")
    titel = "Ferienworkshop läuft noch"
    # Start vor dem Cutoff, Ende danach → muss bleiben
    store.upsert_event(_ev(QUELLE, titel, _d(5, 10), _d(11, 16), nummer=1))
    # komplett vergangen → muss gehen
    store.upsert_event(_ev(QUELLE, "Alter Workshop", _d(5, 10), _d(6, 16), nummer=2))
    cutoff = datetime(2026, 10, 9, 0, 0, tzinfo=__import__("zoneinfo").ZoneInfo("UTC")).isoformat()
    weg = store.prune_stale(QUELLE, cutoff)
    assert weg == 1
    rest = [e["titel"] for e in store.query_events({})]
    assert titel in rest and "Alter Workshop" not in rest
    store.close()


# ---------------------------------------------------------------- Nutzerfund
# 2026-09-24: Nachdem die Umweltkalender-Regel die Uhrzeit aus der Detailseite
# lernt, schrieb der Lauf den Termin mit Zeit neu — der alte ganztägige Satz
# desselben Tages stand aber nach `start_local` vorn und blieb als „frühester"
# der Kette stehen, der neue Satz wurde als überlappender Zwilling gelöscht.
# Messung live: 976 frisch geschriebene Termine, davon 777 sofort entfernt,
# Bestand unverändert ganztägig (1144 von 1232). Regel: gleicher Tag, ein
# ganztägiger Platzhalter gegen einen Eintrag mit Uhrzeit → Platzhalter geht.

def test_ganztaegiger_platzhalter_verliert_gegen_uhrzeit(tmp_path):
    store = Store(tmp_path / "events.db")
    t = "Bauernmarkt Wittenbergplatz"
    store.upsert_event(_ev(QUELLE, t, _d(24, 0), _d(25, 0), nummer=1, ganztags=True))
    store.upsert_event(_ev(QUELLE, t, _d(24, 10), _d(24, 16), nummer=2))

    weg = store.entferne_ueberlappende_zwillinge(QUELLE)

    assert len(weg) == 1, weg
    rest = [e for e in store.query_events({}) if e["titel"] == t]
    assert len(rest) == 1, rest
    assert not rest[0]["ganztags"], "Der Termin MIT Uhrzeit muss bleiben"
    assert rest[0]["start_local"].endswith("T10:00:00")
    store.close()


def test_beruehrende_slots_zweier_zeiten_bleiben(tmp_path):
    """Kontrolle: zwei echte Zeitfenster am selben Tag sind keine Dubletten.

    ZLB-Stundenblöcke (09–10 Uhr, 10–11 Uhr) dürfen auch von der neuen
    Tages-Regel nicht zusammengefasst werden — dort ist KEIN Platzhalter dabei.
    """
    store = Store(tmp_path / "events.db")
    t = "Vorlesestunde"
    store.upsert_event(_ev(QUELLE, t, _d(24, 9), _d(24, 10), nummer=1))
    store.upsert_event(_ev(QUELLE, t, _d(24, 10), _d(24, 11), nummer=2))

    weg = store.entferne_ueberlappende_zwillinge(QUELLE)

    assert weg == []
    assert len([e for e in store.query_events({}) if e["titel"] == t]) == 2
    store.close()


def test_zwei_identische_ganztaegige_saetze_vereint_schon_das_schreiben(tmp_path):
    """Kontrolle: zwei identische ganztägige Sätze kommen gar nicht erst doppelt an.

    `upsert_event` vereint denselben Termin (gleicher Tag, gleiche Zeit, gleicher
    Titel/Ort) beim Schreiben — für das Dedup bleibt hier nichts zu tun. Wichtig
    für den Nutzerfund: genau das passiert bei „ganztags + Uhrzeit" NICHT (der
    Tag stimmt, die Uhrzeit nicht), deshalb musste die Tages-Regel her.
    """
    store = Store(tmp_path / "events.db")
    t = "Dauerausstellung"
    store.upsert_event(_ev(QUELLE, t, _d(24, 0), _d(25, 0), nummer=1, ganztags=True))
    store.upsert_event(_ev(QUELLE, t, _d(24, 0), _d(25, 0), nummer=2, ganztags=True))

    assert len([e for e in store.query_events({}) if e["titel"] == t]) == 1
    assert store.entferne_ueberlappende_zwillinge(QUELLE) == []
    store.close()


def test_ganztaegige_serie_verschiedener_tage_bleibt(tmp_path):
    """Kontrolle: aufeinanderfolgende Tage sind keine Zwillinge."""
    store = Store(tmp_path / "events.db")
    t = "Bauernmarkt Wittenbergplatz"
    store.upsert_event(_ev(QUELLE, t, _d(24, 0), _d(25, 0), nummer=1, ganztags=True))
    store.upsert_event(_ev(QUELLE, t, _d(31, 0), _d(1, 0, monat=11), nummer=2, ganztags=True))

    weg = store.entferne_ueberlappende_zwillinge(QUELLE)

    assert weg == []
    assert len([e for e in store.query_events({}) if e["titel"] == t]) == 2
    store.close()


# ---------------------------------------------------------------- Nutzerfund
# 2026-09-24, zweiter Teil: `industriekultur-berlin` stand mit 236 Terminen im
# Bestand, davon 105 ganztägig — obwohl der Lauf sie nie neu schrieb (die Quelle
# lieferte seit dem Umzug der Übersicht 0 Treffer, `anomalie-0-events`).
# Ursache der Alt-Dubletten: Wird ein Termin nachträglich präzisiert, steckt die
# Startzeit in der Termin-ID (`<slug>#20260924T1600`) → neue ID → INSERT statt
# UPDATE. Der alte ganztägige Platzhalter bleibt unter seiner alten ID stehen
# und trägt dabei meist einen schlechteren Ort („Ohne Angabe") — er lag deshalb
# in einem anderen (Titel, Ort)-Topf und wurde von der Tages-Regel nie gesehen.
# Messung an der Produktions-DB: 102 solche Alt-Dubletten (3 weitere haben nach
# einer Titeländerung der Quelle „AUSGEBUCHT: …" keinen exakten Zwilling und
# werden über `entferne_nicht_mehr_angeboten`/`prune_stale` abgeräumt),
# 0 Fremdtreffer in allen anderen Quellen.

def test_ganztaegiger_platzhalter_verliert_auch_bei_anderem_ort(tmp_path):
    store = Store(tmp_path / "events.db")
    t = "After Work Radtour: Warmes Licht und kühles Bier"
    store.upsert_event(_ev(QUELLE, t, _d(24, 0), _d(24, 23), ort="Ohne Angabe",
                           nummer=1, ganztags=True))
    store.upsert_event(_ev(QUELLE, t, _d(24, 16), None, ort="Start: Hauptbahnhof",
                           nummer=2))

    weg = store.entferne_ueberlappende_zwillinge(QUELLE)

    assert len(weg) == 1, weg
    rest = [e for e in store.query_events({}) if e["titel"] == t]
    assert len(rest) == 1, rest
    assert rest[0]["start_local"].endswith("T16:00:00")
    assert rest[0]["ort"] == "Start: Hauptbahnhof"
    store.close()


def test_gleicher_titel_anderer_ort_mit_zeit_bleibt(tmp_path):
    """Kontrolle: die Tages-Regel greift nur gegen den ganztägigen Platzhalter.

    Zwei echte Zeitfenster desselben Titels an verschiedenen Orten sind keine
    Dublette — sonst würde die Erweiterung über (Titel, Tag) echte Parallel-
    Termine löschen.
    """
    store = Store(tmp_path / "events.db")
    t = "Keramikwerkstatt"
    store.upsert_event(_ev(QUELLE, t, _d(24, 10), _d(24, 12), ort="Haus A", nummer=1))
    store.upsert_event(_ev(QUELLE, t, _d(24, 14), _d(24, 16), ort="Haus B", nummer=2))

    assert store.entferne_ueberlappende_zwillinge(QUELLE) == []
    assert len([e for e in store.query_events({}) if e["titel"] == t]) == 2
    store.close()


def test_manuell_gepflegter_platzhalter_bleibt_auch_bei_anderem_ort(tmp_path):
    """Der Admin-Schutz gilt weiter: manuell=1 wird nie als Dublette gelöscht."""
    store = Store(tmp_path / "events.db")
    t = "Zeitreise Anhalter Bahnhof"
    store.upsert_event(_ev(QUELLE, t, _d(24, 0), _d(24, 23), ort="Ohne Angabe",
                           nummer=1, ganztags=True, manuell=1))
    store.upsert_event(_ev(QUELLE, t, _d(24, 16), None, ort="Start: Hauptbahnhof",
                           nummer=2))

    assert store.entferne_ueberlappende_zwillinge(QUELLE) == []
    assert len([e for e in store.query_events({}) if e["titel"] == t]) == 2
    store.close()


def test_status_vorsatz_verhindert_die_tages_dublette_nicht(tmp_path):
    """„AUSGEBUCHT: …“ und „…“ sind derselbe Termin.

    Die Quelle hängt dem Titel einen Status an und ändert ihn zwischen Läufen:
    der alte ganztägige Satz hieß „Alte Verkehrswege im Südwesten“, der neue
    mit Uhrzeit „AUSGEBUCHT: Alte Verkehrswege im Südwesten“. Gemessen an der
    Produktiv-DB 2026-09-24: genau 3 solche Reste blieben nach dem ersten
    Lauf stehen.
    """
    store = Store(tmp_path / "events.db")
    store.upsert_event(_ev(QUELLE, "Alte Verkehrswege im Südwesten", _d(24, 0),
                           _d(24, 23), ort="Ohne Angabe", nummer=1, ganztags=True))
    store.upsert_event(_ev(QUELLE, "AUSGEBUCHT: Alte Verkehrswege im Südwesten",
                           _d(24, 10), None, ort="14 km Wanderung", nummer=2))

    weg = store.entferne_ueberlappende_zwillinge(QUELLE)

    assert len(weg) == 1, weg
    rest = store.query_events({})
    assert len(rest) == 1, rest
    assert rest[0]["start_local"].endswith("T10:00:00")
    store.close()


def test_titel_kern_streift_nur_den_status_vorsatz():
    assert titel_kern("AUSGEBUCHT: Alte Verkehrswege im Südwesten") == \
        "alte verkehrswege im südwesten"
    assert titel_kern("ausgebucht – Bunkermythen") == "bunkermythen"
    assert titel_kern("Abgesagt: Stadtführung") == "stadtführung"
    assert titel_kern("Alte Verkehrswege im Südwesten") == \
        "alte verkehrswege im südwesten"
    assert titel_kern(None) == ""
    # Kein Vorsatz, kein Eingriff: ein Titel, der nur so ANFÄNGT, bleibt ganz.
    assert titel_kern("Ausgebuchtsein für Anfänger") == "ausgebuchtsein für anfänger"
