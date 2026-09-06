import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

FIXTURES = Path(__file__).parent / "fixtures" / "jup-berlin"


@pytest.fixture()
def fixture_dir() -> Path:
    return FIXTURES


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
