# Change 009 — Umsetzung (2026-09-12, live)

## Was gebaut wurde
- `app/geo.py::_adresse_normalisieren()`: Komposita-Suffix „…str." → „…straße",
  Wortteil „Str." → „Straße", „Pl." → „Platz", Stadt-Token case-insensitiv,
  „Deutschland" am Ende entfernt, Whitespace normalisiert.
- `adresse_amtlich()` normalisiert **vor** `_adresse_teile()`; die normalisierte
  Form ist Suchschlüssel **und** CQL-Wert (Schreibvarianten teilen einen
  Cache-Eintrag). Die angezeigte Adresse bleibt die Quellangabe.

## Motiv (Messung am Berliner WFS, 2026-09-12)
- `str_name='Distelfalterstr.' AND hnr='41' AND plz='12683'` → **0 Treffer**
- `str_name='Distelfalterstraße' …` → **1 Treffer**
- gleiche Signatur bei „Konrad-Wolf-Str./-Straße 39, 13055" und
  „Rheinstr./Rheinstraße 1, 12159".

## Verifikation (Produktion)
- KKK-Events ohne Koordinaten: **77 → 35** (Lauf `ok`, `n_geaendert 42`).
- Bezirksverteilung jetzt: Mitte 67, Lichtenberg 27, Friedrichshain-Kreuzberg 21,
  Tempelhof-Schöneberg 20 (vorher: 77 ohne Bezirk).
- Regressionsprobe per Bilanz: Bestand-Events mit Koordinaten 1237 → 1279
  (+42 = genau der KKK-Zugewinn) → keine andere Quelle hat Positionen verloren.
- Dubletten/Überlappungen weiterhin 0; Milchhäuschen 1 Eintrag; ZLB-Slots intakt.
- Tests: `tests/test_adresse_normalisierung.py` (6 Fälle), Suite 154 grün.

## Was bewusst offen bleibt (35 Events)
- **27 Events ohne jede Adresse** — die Quelle nennt weder Ort noch Adresse.
- **8 Events auf 4 Adressen**, die auch normalisiert nicht auflösen:
  - eingeschobener Ortsname: „Blücherplatz 1 Zentral- und Landesbibliothek
    Berlin (ZLB) 10961 Berlin", „Immanuelkirchstraße 1 Kapelle 10405 Berlin"
  - Quell-Tippfehler im Straßennamen: „Robert-W.-**Klempner**-Str. 1 14167 Berlin"
    (amtlich existiert „Robert-W.-**Kempner**-Straße"; falsche Straße wird nicht
    geraten)
  - Adresse existiert amtlich nicht: „Ruheplatzstraße 12 13347 Berlin"
    (Langform geprüft, 0 Treffer)
