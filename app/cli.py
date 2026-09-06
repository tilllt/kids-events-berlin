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


if __name__ == "__main__":
    sys.exit(main())
