"""CLI: python -m app.cli scrape [--offline] [--no-geo] [--db PATH] [--quelle NAME]
     python -m app.cli stats [--db PATH]
"""
from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="kids-events-berlin")
    sub = p.add_subparsers(dest="cmd", required=True)

    sc = sub.add_parser("scrape", help="Einen Scrape-Lauf ausführen")
    sc.add_argument("--quelle", default="jup-berlin")
    sc.add_argument("--db", default="data/events.db")
    sc.add_argument("--offline", action="store_true",
                    help="Gegen Fixture-HTML laufen (Tests, kein Netz)")
    sc.add_argument("--no-geo", action="store_true", help="Bezirk-Auflösung aus")
    sc.add_argument("--max-details", type=int, default=None)
    sc.set_defaults(fn=cmd_scrape)

    st = sub.add_parser("stats", help="Store-Statistik")
    st.add_argument("--db", default="data/events.db")
    st.set_defaults(fn=cmd_stats)

    isc = sub.add_parser("import-schulen",
                         help="WFS-Schulstamm (GeoJSON) → schulen-Tabelle")
    isc.add_argument("--db", default="data/events.db")
    isc.add_argument("--json", required=True,
                     help="Pfad zum WFS-GeoJSON-Dump (schulen_all.json)")
    isc.set_defaults(fn=cmd_import_schulen)

    itc = sub.add_parser("import-termine",
                         help="Crawl-Termin-Funde → termine_manuell (ungeprueft)")
    itc.add_argument("--db", default="data/events.db")
    itc.add_argument("--json", required=True,
                     help="Pfad zum Crawl-Ergebnis (strato_termin_out.json)")
    itc.set_defaults(fn=cmd_import_termine)

    isz = sub.add_parser("import-schulzweig",
                         help="Mapping {bsn: IDSchulzweig} → schulen.schulzweig_id")
    isz.add_argument("--db", default="data/events.db")
    isz.add_argument("--json", required=True,
                     help="Pfad zum Mapping (bsn_schulzweig.json)")
    isz.set_defaults(fn=cmd_import_schulzweig)

    rec = sub.add_parser("recherche-schulen",
                         help="LLM-Recherche: Tag der offenen Tür auf Schul-Webseiten")
    rec.add_argument("--db", default="data/events.db")
    rec.add_argument("--limit", type=int, default=20,
                     help="Anzahl Schulen (nie geprüfte zuerst)")
    rec.add_argument("--bsn", default=None, help="Nur diese eine Schule prüfen")
    rec.add_argument("--bezirk", default=None,
                     help="Nur Schulen eines Bezirks (z. B. friedrichshain-kreuzberg)")
    rec.add_argument("--schulform", default=None, help="Nur diese Schulform (z. B. Grundschule)")
    rec.add_argument("--dry-run", action="store_true",
                     help="Nur prüfen und berichten, nichts in die Queue schreiben")
    rec.add_argument("--json-out", default=None, help="Ergebnis als JSON ablegen")
    rec.set_defaults(fn=cmd_recherche_schulen)

    dd = sub.add_parser("dedupe-audit",
                        help="Dieselbe Veranstaltung bei mehreren Quellen finden/zusammenführen")
    dd.add_argument("--db", default="data/events.db")
    dd.add_argument("--apply", action="store_true",
                    help="Zusammenführen (ohne Flag: nur Bericht)")
    dd.add_argument("--quelle", default=None, help="Nur diese Quelle betrachten")
    dd.add_argument("--json-out", default=None)
    dd.set_defaults(fn=cmd_dedupe_audit)

    args = p.parse_args(argv)
    return args.fn(args)


def cmd_scrape(args) -> int:
    from .pipeline import run_cli
    return run_cli(args.quelle, args.db, online=not args.offline,
                   geo=not args.no_geo, max_details=args.max_details)


def cmd_stats(args) -> int:
    from .store import Store
    s = Store(args.db)
    try:
        n = s.count_events()
        print(f"events: {n}")
        for r in s.recent_runs("jup-berlin", limit=10):
            print(f"run {r['id']}: {r['quelle']} status={r['status']} "
                  f"events={r['n_events']} neu={r['n_neu']} geaendert={r['n_geaendert']} "
                  f"fehler={r['n_fehler']} seiten={r['n_quellseiten']} dauer={r['dauer_s']:.1f}s")
        return 0
    finally:
        s.close()


def cmd_import_schulen(args) -> int:
    from .schul_import import import_schulen
    from .store import Store
    s = Store(args.db)
    try:
        erg = import_schulen(s, args.json)
        print(f"Schulen-Import: {erg['importiert']} importiert/aktualisiert "
              f"({erg['allgemeinbildend_im_dump']} allgemeinbildend im Dump, "
              f"{erg['uebersprungen']} nicht-allgemeinbildend übersprungen)")
        return 0
    finally:
        s.close()


def cmd_import_termine(args) -> int:
    from .schul_import import import_crawl_termine
    from .store import Store
    s = Store(args.db)
    try:
        erg = import_crawl_termine(s, args.json)
        print(f"Termin-Import: {erg['importiert']} importiert (ungeprueft), "
              f"{erg['duplikate']} Duplikate, {erg['verworfen_alt_oder_rauschen']} "
              f"verworfen (alt/Rauschen), {erg['schulen_mit_funden']} Schulen mit Funden")
        return 0
    finally:
        s.close()


def cmd_import_schulzweig(args) -> int:
    from .schul_import import import_schulzweig_ids
    from .store import Store
    s = Store(args.db)
    try:
        erg = import_schulzweig_ids(s, args.json)
        print(f"Schulzweig-Import: {erg['aktualisiert']} aktualisiert "
              f"({erg['mapping_eintraege']} Mapping-Einträge, "
              f"{erg['bsn_unbekannt']} BSN nicht in DB)")
        return 0
    finally:
        s.close()


def cmd_recherche_schulen(args) -> int:
    """LLM-Recherche als CLI-Lauf (auch für den Scheduler/Cron nutzbar)."""
    import json as _json
    from .recherche import kern
    from .store import Store
    s = Store(args.db)
    try:
        zusammen = kern.lauf(s, limit=args.limit, nur_bsn=args.bsn,
                             dry_run=args.dry_run, bezirk=args.bezirk,
                             schulform=args.schulform)
    finally:
        s.close()
    status = ", ".join(f"{k}={v}" for k, v in sorted(zusammen["status"].items()))
    print(f"Recherche: {zusammen['geprueft']} Schulen geprüft, "
          f"{zusammen['llm_calls']} LLM-Aufrufe, {zusammen['belegt']} belegte Vorschläge, "
          f"{zusammen['dauer_s']}s")
    print(f"Status: {status or '—'}")
    if zusammen["verworfen"]:
        print("Verworfen: " + ", ".join(f"{k}×{v}" for k, v in zusammen["verworfen"].items()))
    for e in zusammen["schulen"]:
        zeile = f"  {e['bsn']} {e['status']:<11} belegt={e['n_belegt']}/{e['n_roh']}"
        if e.get("grund"):
            zeile += f" · {e['grund'][:90]}"
        print(zeile)
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            _json.dump(zusammen, f, ensure_ascii=False, indent=1)
        print(f"Ergebnis: {args.json_out}")
    return 0


def cmd_dedupe_audit(args) -> int:
    """Bericht (und optional Zusammenführung) quellenübergreifender Dubletten."""
    import json as _json
    from .store import Store
    s = Store(args.db)
    try:
        erg = s.merge_doppelte_events(dry_run=not args.apply, nur_quelle=args.quelle)
    finally:
        s.close()
    print(f"Dubletten-Prüfung: {erg['geprueft']} Events, {erg['gruppen']} Gruppen, "
          f"{erg['entfernbar']} überzählige Datensätze, {erg['verdacht']} Verdachtsfälle"
          + ("" if args.apply else " (Probelauf — nichts geändert)"))
    for b in erg["beispiele"]:
        print(f"  behalten: {b['behalten'][:60]} ({b['behalten_quelle']})")
        for e in b["entfernt"]:
            print(f"    entfernt: {e['titel'][:60]} ({e['quelle']})")
    if erg["verdachtsfaelle"]:
        print("  Verdacht (nicht gemergt):")
        for v in erg["verdachtsfaelle"]:
            print(f"    {v['datum']} {v['titel'][:55]} · {v['grund']}")
    if args.apply:
        print(f"Zusammengeführt: {erg['entfernt']} entfernt, "
              f"{erg['felder_ergaenzt']} Felder ergänzt")
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            _json.dump(erg, f, ensure_ascii=False, indent=1)
        print(f"Bericht: {args.json_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
