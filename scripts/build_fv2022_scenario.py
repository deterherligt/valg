#!/usr/bin/env python3
"""
Build FV2022 demo scenario wave data.

Usage:
    python scripts/build_fv2022_scenario.py [--force]

Downloads FV2026 geography + candidates from SFTP and FV2022 vote results
from the valg.dk API, then writes pre-baked wave directories to
valg/scenarios/fv2022/.

Options:
    --force   Re-download even if cache files exist
"""
from __future__ import annotations

import csv
import json
import math
import shutil
import sys
import unicodedata
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
CACHE_DIR = Path(__file__).parent / ".cache"
OUTPUT_DIR = REPO_ROOT / "valg" / "scenarios" / "fv2022"

FV2026_SFTP_PATH = "/data/folketingsvalg-135-24-03-2026"
FV2022_CSV_URL = (
    "https://valg.dk/api/export-data/export-fv-data-csv"
    "?electionId=987875fe-0dae-42ac-be5b-62cf0bd5d65e"
)

# Wall-clock times per wave index (index 0 = wave_00, index 1 = wave_01, ...)
WAVE_TIMES = [
    "20:00",  # 00 setup
    "21:03",  # 01 tiny islands
    "21:11",  # 02
    "21:19",  # 03
    "21:28",  # 04
    "21:38",  # 05
    "21:50",  # 06
    "22:02",  # 07
    "22:14",  # 08
    "22:24",  # 09
    "22:33",  # 10
    "22:41",  # 11
    "22:48",  # 12
    "22:54",  # 13
    "22:59",  # 14
    "23:05",  # 15
    "23:11",  # 16
    "23:18",  # 17
    "23:25",  # 18
    "23:32",  # 19
    "23:39",  # 20
    "23:46",  # 21
    "23:52",  # 22
    "23:57",  # 23
    "00:04",  # 24
    "00:12",  # 25
    "00:22",  # 26
    "00:40",  # 27
    "01:02",  # 28
    "01:28",  # 29
    "01:58",  # 30
    "02:31",  # 31
    "03:10",  # 32
]

# Interval in seconds between waves at 1x speed
WAVE_INTERVALS = [
    0,    # 00 setup — immediate
    45,   # 01
    45,   # 02
    45,   # 03
    45,   # 04
    45,   # 05
    45,   # 06
    45,   # 07
    45,   # 08
    45,   # 09
    45,   # 10
    45,   # 11
    45,   # 12
    45,   # 13
    45,   # 14
    45,   # 15
    45,   # 16
    45,   # 17
    45,   # 18
    45,   # 19
    45,   # 20
    45,   # 21
    45,   # 22
    45,   # 23
    45,   # 24
    45,   # 25
    60,   # 26 fintaelling
    60,   # 27
    75,   # 28
    75,   # 29
    90,   # 30
    90,   # 31
    90,   # 32
]

# Storkreds codes whose AOs are placed in wave_01 regardless of size
ISLAND_STORKREDS_CODES = {"10"}   # Bornholms Storkreds

# Opstillingskreds names (normalised) that are island-area and go in wave_01
ISLAND_OK_NAMES = {
    "laesoekredsen", "laesoe",
    "samsoekredsen", "samsoe",
    "aeroekredsen", "aeroe",
    "fanoekredsen", "fanoe",
    "anholtkredsen", "anholt",
}


# ── Pure helper functions ─────────────────────────────────────────────────────

def normalize_name(s: str) -> str:
    """Lowercase, apply Danish romanisation, strip remaining diacritics, collapse whitespace."""
    s = s.strip().lower()
    s = s.replace("\xe6", "ae").replace("\xf8", "oe").replace("\xe5", "aa")
    s = "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
    s = " ".join(s.split())
    return s


def distribute_candidate_votes(party_total: int, candidates: list[dict]) -> list[int]:
    """Distribute party_total votes across candidates using 35%/power-decay algorithm.

    Position 1 gets 35% of votes. Remaining 65% split with weight 1/pos^0.7.
    Returns list of vote counts in same order as candidates.
    Guarantees sum == party_total (remainder assigned to position 1).
    """
    if not candidates:
        return []
    if party_total == 0:
        return [0] * len(candidates)

    n = len(candidates)
    result = [0] * n

    if n == 1:
        result[0] = party_total
        return result

    kredskandidat_votes = int(party_total * 0.35)
    remainder = party_total - kredskandidat_votes

    weights = [1.0 / (c["ballot_position"] ** 0.7) for c in candidates[1:]]
    total_weight = sum(weights)

    assigned = 0
    for i, w in enumerate(weights):
        votes = int(remainder * w / total_weight)
        result[i + 1] = votes
        assigned += votes

    result[0] = kredskandidat_votes + (remainder - assigned)
    return result


def build_partistemmefordeling(ok_id: str, party_totals: dict[str, int]) -> dict:
    """Build a partistemmefordeling JSON structure for one opstillingskreds."""
    return {
        "Valg": {
            "OpstillingskredsId": str(ok_id),
            "Partier": [
                {"PartiId": pid, "Stemmer": votes}
                for pid, votes in party_totals.items()
            ],
        }
    }


def build_valgresultater(
    ao_id: str,
    optaellingstype: str,
    party_data: dict[str, dict],
    ao_ok_id: str,
) -> dict:
    """Build a valgresultater JSON structure for one AO.

    party_data: {party_id: {"total": int, "candidates_by_ok": {ok_id: [{"id", "ballot_position"}]}}}
    ao_ok_id: the opstillingskreds this AO belongs to (for candidate lookup)
    """
    inden_for_parti = []

    for party_id, pdata in party_data.items():
        total = pdata["total"]
        candidates = pdata["candidates_by_ok"].get(ao_ok_id, [])
        vote_dist = distribute_candidate_votes(total, candidates)

        kandidater = [
            {"KandidatId": str(c["id"]), "Stemmer": vote_dist[i]}
            for i, c in enumerate(candidates)
        ]

        inden_for_parti.append({
            "PartiId": party_id,
            "Partistemmer": total,
            "Kandidater": kandidater,
        })

    return {
        "Valgresultater": {
            "AfstemningsomraadeId": str(ao_id),
            "Optaellingstype": optaellingstype,
            "IndenforParti": inden_for_parti,
            "KandidaterUdenforParti": [],
        }
    }


# ── Download ──────────────────────────────────────────────────────────────────

def download_sftp_dir(
    sftp,
    remote_dir: str,
    local_dir: Path,
    force: bool = False,
) -> int:
    """Recursively download all files from remote_dir to local_dir.

    Returns count of files downloaded (skipped cached files not counted).
    """
    local_dir.mkdir(parents=True, exist_ok=True)
    downloaded = 0
    for entry in sftp.listdir_attr(remote_dir):
        remote_path = f"{remote_dir}/{entry.filename}"
        local_path = local_dir / entry.filename
        import stat as stat_module
        if stat_module.S_ISDIR(entry.st_mode):
            downloaded += download_sftp_dir(sftp, remote_path, local_path, force=force)
        else:
            if not force and local_path.exists():
                continue
            sftp.get(remote_path, str(local_path))
            downloaded += 1
    return downloaded


def download_fv2026_geografi(force: bool = False) -> None:
    """Download FV2026 geografi files from SFTP into cache."""
    import paramiko
    local_geo = CACHE_DIR / "fv2026" / "geografi"
    local_geo.mkdir(parents=True, exist_ok=True)

    # Check if already cached
    if not force and any(local_geo.glob("*.json")):
        print(f"  using cached fv2026/geografi/ ({len(list(local_geo.glob('*.json')))} files)")
        return

    print("  downloading fv2026/geografi from SFTP …")
    transport = paramiko.Transport(("data.valg.dk", 22))
    transport.connect(username="Valg", password="Valg")
    sftp = paramiko.SFTPClient.from_transport(transport)
    try:
        count = download_sftp_dir(sftp, f"{FV2026_SFTP_PATH}/geografi", local_geo, force=force)
        print(f"  downloaded {count} geografi files")
    finally:
        sftp.close()
        transport.close()


def download_fv2026_kandidatdata(force: bool = False) -> None:
    """Download FV2026 kandidat-data files from SFTP into cache."""
    import paramiko
    local_kd = CACHE_DIR / "fv2026" / "kandidat-data"
    local_kd.mkdir(parents=True, exist_ok=True)

    if not force and any(local_kd.glob("*.json")):
        print(f"  using cached fv2026/kandidat-data/ ({len(list(local_kd.glob('*.json')))} files)")
        return

    print("  downloading fv2026/kandidat-data from SFTP …")
    transport = paramiko.Transport(("data.valg.dk", 22))
    transport.connect(username="Valg", password="Valg")
    sftp = paramiko.SFTPClient.from_transport(transport)
    try:
        count = download_sftp_dir(sftp, f"{FV2026_SFTP_PATH}/kandidat-data", local_kd, force=force)
        print(f"  downloaded {count} kandidat-data files")
    finally:
        sftp.close()
        transport.close()


def download_fv2022_csv(force: bool = False) -> None:
    """Download FV2022 results CSV from valg.dk API into cache."""
    import urllib.request
    csv_path = CACHE_DIR / "fv2022_results.csv"
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    if not force and csv_path.exists():
        size_kb = csv_path.stat().st_size // 1024
        print(f"  using cached fv2022_results.csv ({size_kb} KB)")
        return

    print("  downloading fv2022_results.csv from valg.dk …")
    with urllib.request.urlopen(FV2022_CSV_URL, timeout=60) as resp:
        data = resp.read()
    csv_path.write_bytes(data)
    print(f"  downloaded fv2022_results.csv ({len(data) // 1024} KB)")


def download_all(force: bool = False) -> None:
    """Download all required data into cache. Skip if already cached (unless force=True)."""
    print("Phase 1: Downloading data …")
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    download_fv2026_geografi(force=force)
    download_fv2026_kandidatdata(force=force)
    download_fv2022_csv(force=force)
    print()


# ── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    force = "--force" in sys.argv
    print("Build script not yet complete — run after all tasks are implemented.")
