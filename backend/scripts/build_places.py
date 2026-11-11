"""Regenerate hackmash/data/places_in.tsv.gz, the list of Indian places geo.py looks cities up in.

    cd backend && uv run python scripts/build_places.py

Source: GeoNames (https://www.geonames.org/, CC BY 4.0), every place in India
with more than 5,000 people: its name, state, coordinates, population and the
Latin-script names platforms also use ("Bangalore", "Gurgaon"). One line per
place: name, state, lat, lng, population, other names joined by "|".
"""

from __future__ import annotations

import gzip
import io
import sys
import zipfile
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hackmash.geo import PLACES_FILE, canonical_state, fold  # noqa: E402

CITIES = "https://download.geonames.org/export/dump/cities5000.zip"
ADMIN1 = "https://download.geonames.org/export/dump/admin1CodesASCII.txt"

# GeoNames name -> the name students and platforms use today
DISPLAY = {
    "Bangalore": "Bengaluru", "Gurgaon": "Gurugram", "Dehra Dun": "Dehradun", "Mangalore": "Mangaluru",
    "Calcutta": "Kolkata", "Bombay": "Mumbai", "Madras": "Chennai", "Trivandrum": "Thiruvananthapuram",
    "Udagamandalam": "Ooty", "Ootacamund": "Ooty", "Sahibzada Ajit Singh Nagar": "Mohali",
    "Raurkela": "Rourkela", "Panjim": "Panaji", "Madgaon": "Margao", "Mysore": "Mysuru",
    "Vizag": "Visakhapatnam", "Pondicherry": "Puducherry", "Baroda": "Vadodara", "Cochin": "Kochi",
    "Allahabad": "Prayagraj", "Gulbarga": "Kalaburagi", "Belgaum": "Belagavi", "Tumkur": "Tumakuru",
}


def main() -> None:
    with httpx.Client(timeout=120, follow_redirects=True) as client:
        admin1 = {}
        for line in client.get(ADMIN1).raise_for_status().text.splitlines():
            code, name, *_ = line.split("\t")
            admin1[code] = name
        archive = zipfile.ZipFile(io.BytesIO(client.get(CITIES).raise_for_status().content))
    rows, skipped = [], 0
    for line in archive.read("cities5000.txt").decode("utf-8").splitlines():
        f = line.split("\t")
        if f[8] != "IN":
            continue
        state = canonical_state(admin1.get(f"IN.{f[10]}"))
        if not state:
            skipped += 1
            continue
        name = DISPLAY.get(f[2], f[2]) or f[1]
        others = {fold(n) for n in (f[1], f[2], *f[3].split(","))} - {fold(name), ""}
        others = {n for n in others if 3 <= len(n) <= 40 and any(c.isalpha() for c in n)}
        rows.append((name, state, f"{float(f[4]):.4f}", f"{float(f[5]):.4f}", f[14] or "0", "|".join(sorted(others))))
    rows.sort(key=lambda r: (r[1], -int(r[4]), r[0]))
    PLACES_FILE.parent.mkdir(parents=True, exist_ok=True)
    body = "\n".join("\t".join(r) for r in rows).encode("utf-8")
    PLACES_FILE.write_bytes(gzip.compress(body, mtime=0))
    print(f"{len(rows)} places ({skipped} without a known state) -> {PLACES_FILE} ({PLACES_FILE.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
