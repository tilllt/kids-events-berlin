#!/usr/bin/env python3
"""BSN → IDSchulzweig-Mapping für alle Schulen (bildung.berlin.de).

Der WFS-Stamm (schulen_all.json) liefert BSN, aber die offiziellen
Schulportraits hängen an IDSchulzweig. Das Schulverzeichnis redirectet
SchulListe.aspx?Sort=Schulname&Suchbegriff=<BSN> direkt auf das Portrait
(?IDSchulzweig=…). Redirect-Link via 302-Location abgegriffen.

Nur stdlib (läuft auch auf dem Containerhost .50). Sanft: 1 Request/Sek.,
Resume-JSON bsn_schulzweig.json neben dem Skript. Ergebnis: {bsn: id}.
"""
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

UA = ("Mozilla/5.0 (compatible; KinderEventsBerlin/0.1; "
      "+https://kinderkram.cia-spandau.de)")
URL = ("https://www.bildung.berlin.de/Schulverzeichnis/"
       "SchulListe.aspx?Sort=Schulname&Suchbegriff={bsn}")
OUT = Path(__file__).resolve().parent / "bsn_schulzweig.json"


def lade_schulen(path: Path) -> list[str]:
    d = json.loads(path.read_text(encoding="utf-8"))
    feats = d.get("features", d if isinstance(d, list) else [])
    bsns = []
    for f in feats:
        p = f.get("properties", {})
        bsn = str(p.get("bsn") or "").strip()
        schulart = str(p.get("schulart") or "").strip()
        if bsn and schulart in ("Grundschule", "Integrierte Sekundarschule",
                                "Gymnasium", "Gemeinschaftsschule"):
            bsns.append(bsn)
    return sorted(set(bsns))


class _KeinRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # 302 NICHT folgen — Location-Header reicht


def hole_id(bsn: str) -> str | None:
    opener = urllib.request.build_opener(_KeinRedirect)
    req = urllib.request.Request(URL.format(bsn=bsn), headers={"User-Agent": UA})
    try:
        with opener.open(req, timeout=25) as r:
            loc = r.headers.get("Location", "")
            m = re.search(r"IDSchulzweig=(\d+)", loc)
            return m.group(1) if m else None
    except urllib.error.HTTPError as e:  # noqa: F821 — Import unten
        # 302/Redirect-Code: Location-Header trägt die ID
        loc = e.headers.get("Location", "")
        m = re.search(r"IDSchulzweig=(\d+)", loc)
        return m.group(1) if m else None
    except Exception:  # noqa: BLE001
        return None


def main() -> int:
    schul_json = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("schulen_all.json")
    bsns = lade_schulen(schul_json)
    print(f"{len(bsns)} allgemeinbildende Schulen", flush=True)

    mapping: dict[str, str] = {}
    if OUT.exists():
        mapping = json.loads(OUT.read_text(encoding="utf-8"))
        print(f"Resume: {len(mapping)} schon erfasst", flush=True)

    fehler: list[str] = []
    for i, bsn in enumerate(bsns, 1):
        if str(bsn) in mapping:
            continue
        try:
            hid = hole_id(bsn)
        except Exception as e:  # noqa: BLE001
            hid = None
            print(f"  {bsn}: {e}", flush=True)
        if hid:
            mapping[str(bsn)] = hid
        else:
            fehler.append(bsn)
            print(f"  {bsn}: kein IDSchulzweig", flush=True)
        if i % 10 == 0 or i == len(bsns):
            OUT.write_text(json.dumps(mapping, indent=1, ensure_ascii=False),
                           encoding="utf-8")
            print(f"  … {i}/{len(bsns)} abgearbeitet, {len(mapping)} gemappt",
                  flush=True)
        time.sleep(1.1)
    OUT.write_text(json.dumps(mapping, indent=1, ensure_ascii=False),
                   encoding="utf-8")
    print(f"Fertig: {len(mapping)}/{len(bsns)} gemappt, {len(fehler)} Fehler",
          flush=True)
    return 0 if not fehler else 1


if __name__ == "__main__":
    raise SystemExit(main())
