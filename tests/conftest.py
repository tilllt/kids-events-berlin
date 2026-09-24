import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import os

# Kein echter Netz-Scrape im Testprozess: Der Scheduler würde sonst echte
# Adressen holen und in Tests hineinarbeiten (Ursache der Segfaults, 13.09.).
os.environ.setdefault("KINDERKRAM_SCHEDULER", "0")

FIXTURES = Path(__file__).parent / "fixtures" / "jup-berlin"


@pytest.fixture(autouse=True)
def laufende_laeufe_abwarten():
    """Wartet nach jedem Test auf Hintergrund-Laeufe (Scrape, Recherche).

    Ohne das lief ein Scrape-Thread nach Testende weiter und stiess in einem
    spaeteren Test mit SQLite/lxml zusammen — die Suite brach mit einem
    Segfault ab (Exit 139, 13.09., per Faulthandler gefunden). Wartezeit
    begrenzt, damit ein haengender Lauf die Suite nicht blockiert.
    """
    yield
    # Alle Hintergrund-Laeufe abwarten — nicht nur die des Admin-Knopfs: auch
    # der Scheduler aus main.py startet Scrapes. Läuft so einer in einen
    # spaeteren Test hinein, kollidieren zwei Laeufe auf derselben Datenbank
    # (Segfault im SQLite-/lxml-Zugriff, 13.09.). Zusaetzlich serialisiert
    # pipeline.LAUF_SPERRE die Laeufe selbst.
    import threading
    for t in threading.enumerate():
        if t is threading.current_thread():
            continue
        if t.name.startswith(("scrape-", "schul-recherche")):
            t.join(timeout=25)


@pytest.fixture()
def fixture_dir() -> Path:
    return FIXTURES


@pytest.fixture()
def fixture_dir_zlb() -> Path:
    return Path(__file__).parent / "fixtures" / "zlb"


@pytest.fixture()
def fixture_dir_museumsportal() -> Path:
    return Path(__file__).parent / "fixtures" / "museumsportal"


@pytest.fixture()
def fixture_dir_familienportal() -> Path:
    return Path(__file__).parent / "fixtures" / "familienportal"


@pytest.fixture()
def fixture_dir_tempelhoferfeld() -> Path:
    return Path(__file__).parent / "fixtures" / "tempelhoferfeld"


@pytest.fixture()
def listing_p0() -> str:
    return (FIXTURES / "listing_p0.html").read_text(encoding="utf-8")


@pytest.fixture()
def listing_p1() -> str:
    return (FIXTURES / "listing_p1.html").read_text(encoding="utf-8")


@pytest.fixture()
def detail_fam() -> str:
    return (FIXTURES / "detail_familiensportfest.html").read_text(encoding="utf-8")


@pytest.fixture()
def detail_raetsel() -> str:
    return (FIXTURES / "detail_raetsel.html").read_text(encoding="utf-8")


@pytest.fixture()
def fixture_dir_gaerten_der_welt() -> Path:
    return Path(__file__).parent / "fixtures" / "gaerten-der-welt"


@pytest.fixture()
def fixture_dir_britzer_garten() -> Path:
    return Path(__file__).parent / "fixtures" / "britzer-garten"


@pytest.fixture()
def fixture_dir_suedgelaende() -> Path:
    return Path(__file__).parent / "fixtures" / "suedgelaende"


@pytest.fixture()
def fixture_dir_kinderkulturkalender() -> Path:
    return Path(__file__).parent / "fixtures" / "kinderkulturkalender"


@pytest.fixture()
def fixture_dir_umweltkalender() -> Path:
    return Path(__file__).parent / "fixtures" / "umweltkalender"


@pytest.fixture()
def fixture_dir_industriekultur() -> Path:
    return Path(__file__).parent / "fixtures" / "industriekultur"
