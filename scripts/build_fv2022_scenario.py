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
import re
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

# FV2022 Folketing kredsmandater per storkreds (by Nummer, proportional to opstillingskredse)
# Total: 135 kredsmandater across 10 storkredse
STORKREDS_KREDSMANDATER = {
    1: 18,   # København
    2: 12,   # Københavns Omegn
    3: 9,    # Nordsjælland
    4: 2,    # Bornholm
    5: 18,   # Sjælland
    6: 12,   # Fyn
    7: 19,   # Sydjylland
    8: 16,   # Østjylland
    9: 16,   # Vestjylland
    10: 13,  # Nordjylland
}


# ── Pure helper functions ─────────────────────────────────────────────────────

def normalize_name(s: str) -> str:
    """Lowercase, apply Danish romanisation, strip remaining diacritics, collapse whitespace."""
    s = s.strip().lower()
    s = s.replace("\xe6", "ae").replace("\xf8", "oe").replace("\xe5", "aa")
    s = "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
    s = " ".join(s.split())
    return s


def normalize_ok_name(s: str) -> str:
    """Normalize an opstillingskreds name, stripping suffixes that differ between elections."""
    n = normalize_name(s)
    if n.endswith("kredsen"):
        n = n[:-len("kredsen")]
    # 'omegns' used in FV2022 vs 'omegn' in FV2026
    if n.endswith("omegns"):
        n = n[:-1]
    return n.rstrip()


def normalize_ao_name(s: str) -> str:
    """Normalize an afstemningsomraade name, stripping leading number prefixes used in FV2022.

    Handles formats like '1. Skagen', '31. 7. Brønshøj' (global + local numbering).
    """
    n = normalize_name(s)
    # Strip all leading '<digits>. ' prefixes (some AOs have two levels)
    while re.match(r"^\d+\.\s+\S", n):
        n = re.sub(r"^\d+\.\s+", "", n)
    return n


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


# ── Parse ─────────────────────────────────────────────────────────────────────

def parse_geografi(geografi_dir: Path) -> dict[str, dict]:
    """
    Parse FV2026 geografi files into a hierarchy dict.

    Returns {ao_id: {ao_name, ok_id, ok_name, sk_id, sk_name, eligible_voters}}
    All IDs are strings. ao_id / ok_id are Dagi_id values; sk_id is Nummer.
    """
    # Storkreds: Nummer → Navn
    sk_lookup: dict[str, str] = {}
    # Opstillingskreds: Dagi_id → {name, sk_id}
    ok_lookup: dict[str, dict] = {}

    for f in geografi_dir.glob("*.json"):
        if f.name.endswith(".hash"):
            continue
        data = json.loads(f.read_text())
        if not isinstance(data, list) or not data:
            continue
        item_type = data[0].get("Type", "")
        if item_type == "Storkreds":
            for item in data:
                sk_lookup[str(item["Nummer"])] = item.get("Navn", "")
        elif item_type == "Opstillingskreds":
            for item in data:
                ok_lookup[str(item["Dagi_id"])] = {
                    "name": item.get("Navn", ""),
                    "sk_id": str(item.get("Storkredskode", "")),
                    "ok_nummer": str(item.get("Nummer", "")),
                }

    ao_hierarchy: dict[str, dict] = {}
    for f in geografi_dir.glob("*.json"):
        if f.name.endswith(".hash"):
            continue
        data = json.loads(f.read_text())
        if not isinstance(data, list) or not data:
            continue
        if data[0].get("Type") == "Afstemningsområde":
            for item in data:
                ok_id = str(item.get("Opstillingskreds_Dagi_id", ""))
                ok_info = ok_lookup.get(ok_id, {})
                sk_id = ok_info.get("sk_id", "")
                ao_hierarchy[str(item["Dagi_id"])] = {
                    "ao_name": item.get("Navn", ""),
                    "ok_id": ok_id,
                    "ok_name": ok_info.get("name", ""),
                    "sk_id": sk_id,
                    "sk_name": sk_lookup.get(sk_id, ""),
                    "eligible_voters": item.get("AntalStemmeberettigede", 0) or 0,
                }

    return ao_hierarchy


def parse_kandidatdata(kandidat_dir: Path) -> dict[str, dict[str, list[dict]]]:
    """
    Parse FV2026 kandidat-data files.

    Returns {ok_id: {party_id: [{id, ballot_position}]}} sorted by ballot_position.
    ok_id is OpstillingskredsDagiId (string). party_id is Partibogstav.
    """
    result: dict[str, dict[str, list[dict]]] = {}

    for f in kandidat_dir.glob("*.json"):
        if f.name.endswith(".hash"):
            continue
        data = json.loads(f.read_text())
        for party in data.get("IndenforParti", []):
            party_id = party.get("Partibogstav")
            if not party_id:
                continue
            for k in party.get("Kandidater", []):
                cand_id = str(k.get("Id", ""))
                cand_name = k.get("Navn", "")
                for opstilling in k.get("Opstillingskredse", []):
                    if not opstilling.get("OpstilletIKreds"):
                        continue
                    ok_id = str(opstilling.get("OpstillingskredsDagiId", ""))
                    if not ok_id:
                        continue
                    ballot_pos = opstilling.get("KandidatsPlacering", 99)
                    result.setdefault(ok_id, {}).setdefault(party_id, []).append({
                        "id": cand_id,
                        "name": cand_name,
                        "ballot_position": ballot_pos,
                    })

    for ok_id in result:
        for party_id in result[ok_id]:
            result[ok_id][party_id].sort(key=lambda c: c["ballot_position"])

    return result


def parse_fv2022_csv(csv_path: Path) -> dict[tuple[str, str], dict[str, int]]:
    """
    Parse FV2022 results CSV.

    Returns {(ok_name_norm, ao_name_norm): {party_id: party_votes}}
    Only 'Partiliste' rows are counted.
    """
    result: dict[tuple[str, str], dict[str, int]] = {}
    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            if row.get("Navn", "").strip() != "Partiliste":
                continue
            ok_norm = normalize_ok_name(row.get("Opstillingskreds", ""))
            ao_norm = normalize_ao_name(row.get("Afstemningsområde", ""))
            party_id = row.get("Partibogstav", "").strip()
            try:
                votes = int(row.get("Stemmetal", 0))
            except (ValueError, TypeError):
                continue
            result.setdefault((ok_norm, ao_norm), {})[party_id] = votes
    return result


def parse_fv2022_personal_votes(
    csv_path: Path,
) -> dict[tuple[str, str], dict[str, dict[str, int]]]:
    """
    Parse FV2022 personal vote rows from the CSV.

    Returns {(ok_norm, ao_norm): {party_id: {name_norm: votes}}}
    Skips Partiliste rows (those are party-list votes, not personal votes).
    """
    result: dict[tuple[str, str], dict[str, dict[str, int]]] = {}
    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            navn = row.get("Navn", "").strip()
            if navn == "Partiliste":
                continue
            ok_norm = normalize_ok_name(row.get("Opstillingskreds", ""))
            ao_norm = normalize_ao_name(row.get("Afstemningsområde", ""))
            party_id = row.get("Partibogstav", "").strip()
            name_norm = normalize_name(navn)
            try:
                votes = int(row.get("Stemmetal", 0))
            except (ValueError, TypeError):
                continue
            result.setdefault((ok_norm, ao_norm), {}).setdefault(party_id, {})[name_norm] = votes
    return result


def build_id_mapping(hierarchy: dict[str, dict]) -> dict[tuple[str, str], str]:
    """Build {(ok_name_norm, ao_name_norm): ao_id} from the geografi hierarchy."""
    mapping: dict[tuple[str, str], str] = {}
    for ao_id, info in hierarchy.items():
        key = (normalize_ok_name(info["ok_name"]), normalize_ao_name(info["ao_name"]))
        mapping[key] = ao_id
    return mapping


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



def build_fv2022_kandidatdata_from_csv(
    csv_path: Path,
    geo_dir: Path,
    output_dir: Path,
    force: bool = False,
) -> None:
    """Build FV2022 kandidat-data JSON from CSV personal vote rows + FV2026 geografi.

    Reads candidate names from the CSV (non-Partiliste rows), maps opstillingskreds
    names to Dagi IDs via the geografi files, assigns sequential integer IDs, and
    writes a single kandidat-data JSON file to output_dir.

    Skips if output_dir already contains JSON files (unless force=True).
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    if not force and any(output_dir.glob("*.json")):
        print(f"  using cached fv2022/kandidat-data/ ({len(list(output_dir.glob('*.json')))} files)")
        return

    print("  building fv2022/kandidat-data from CSV …")

    # Build ok_name_norm -> ok_dagi_id mapping from FV2026 geografi
    ok_name_to_id: dict[str, str] = {}
    for f in geo_dir.glob("*.json"):
        if f.name.endswith(".hash"):
            continue
        data = json.loads(f.read_text())
        if not isinstance(data, list) or not data:
            continue
        if data[0].get("Type") == "Opstillingskreds":
            for item in data:
                name_norm = normalize_ok_name(item.get("Navn", ""))
                ok_name_to_id[name_norm] = str(item.get("Dagi_id", ""))

    # Collect candidates: {party_id: {ok_name_norm: set of candidate names}}
    candidates_by_party_ok: dict[str, dict[str, list[str]]] = {}
    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            if row.get("Navn", "").strip() == "Partiliste":
                continue
            party_id = row.get("Partibogstav", "").strip()
            ok_norm = normalize_ok_name(row.get("Opstillingskreds", ""))
            name = row.get("Navn", "").strip()
            if not party_id or not name or not ok_norm:
                continue
            candidates_by_party_ok.setdefault(party_id, {}).setdefault(ok_norm, [])
            if name not in candidates_by_party_ok[party_id][ok_norm]:
                candidates_by_party_ok[party_id][ok_norm].append(name)

    # Build the JSON structure
    next_id = 1
    inden_for_parti = []

    for party_id in sorted(candidates_by_party_ok):
        party_kandidater = []
        for ok_norm, names in sorted(candidates_by_party_ok[party_id].items()):
            ok_dagi_id = ok_name_to_id.get(ok_norm, "")
            if not ok_dagi_id:
                continue
            for pos, name in enumerate(sorted(names), start=1):
                party_kandidater.append({
                    "Id": next_id,
                    "Navn": name,
                    "Opstillingskredse": [{
                        "OpstillingskredsDagiId": ok_dagi_id,
                        "OpstilletIKreds": True,
                        "KandidatsPlacering": pos,
                    }],
                })
                next_id += 1
        inden_for_parti.append({
            "Partibogstav": party_id,
            "Kandidater": party_kandidater,
        })

    out = {"IndenforParti": inden_for_parti}
    (output_dir / "kandidat-data-fv2022.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2)
    )
    n = sum(len(p["Kandidater"]) for p in inden_for_parti)
    print(f"  built kandidat-data-fv2022.json ({n} candidates)")


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
    download_fv2022_csv(force=force)
    build_fv2022_kandidatdata_from_csv(
        csv_path=CACHE_DIR / "fv2022_results.csv",
        geo_dir=CACHE_DIR / "fv2026" / "geografi",
        output_dir=CACHE_DIR / "fv2022" / "kandidat-data",
        force=force,
    )
    print()


# ── Wave assignment ────────────────────────────────────────────────────────────

N_PRELIM_WAVES = 25   # wave_01 ... wave_25
N_FINAL_WAVES = 7     # wave_26 ... wave_32


def assign_preliminary_waves(
    matched_aos: dict[str, dict],
    n_waves: int,
    island_ao_ids: set[str],
) -> dict[str, int]:
    """Assign each AO an integer wave number (1-indexed).

    Island AOs are forced to wave 1. Remaining AOs are sorted by eligible_voters
    ascending and distributed evenly across waves 2..n_waves.
    Returns {ao_id: wave_number}.
    """
    assignment: dict[str, int] = {}

    island = {k for k in matched_aos if k in island_ao_ids}
    non_island = {k: v for k, v in matched_aos.items() if k not in island_ao_ids}

    for ao_id in island:
        assignment[ao_id] = 1

    sorted_aos = sorted(non_island, key=lambda k: non_island[k].get("eligible_voters", 0))
    bucket_size = max(1, math.ceil(len(sorted_aos) / (n_waves - 1)))

    for i, ao_id in enumerate(sorted_aos):
        wave = min(2 + i // bucket_size, n_waves)
        assignment[ao_id] = wave

    return assignment


def detect_island_ao_ids(hierarchy: dict[str, dict]) -> set[str]:
    """Return AO IDs that belong to island opstillingskredse or storkredse."""
    island_ids: set[str] = set()
    for ao_id, info in hierarchy.items():
        ok_norm = normalize_ok_name(info.get("ok_name", ""))
        sk_id = info.get("sk_id", "")
        if ok_norm in ISLAND_OK_NAMES or sk_id in ISLAND_STORKREDS_CODES:
            island_ids.add(ao_id)
    return island_ids


# ── File generation ────────────────────────────────────────────────────────────

def write_wave_00(
    output_dir: Path,
    geografi_dir: Path,
    kandidat_dir: Path,
    storkredse: list[dict],
    opstillingskredse: list[dict],
    all_aos: list[dict],
    parties: list[dict],
) -> None:
    """Write wave_00 setup files: Parti, Storkreds, geografi, kandidat-data."""
    wave_dir = output_dir / "wave_00"
    wave_dir.mkdir(parents=True, exist_ok=True)

    (wave_dir / "_meta.json").write_text(json.dumps({
        "label": "20:00 — Opstilling & geografi",
        "time": "20:00",
        "interval_s": 0.0,
        "phase": "setup",
    }, ensure_ascii=False, indent=2))

    (wave_dir / "Parti-FV2022.json").write_text(
        json.dumps(parties, ensure_ascii=False, indent=2)
    )

    (wave_dir / "Storkreds.json").write_text(
        json.dumps(storkredse, ensure_ascii=False, indent=2)
    )

    geo_out = wave_dir / "geografi"
    geo_out.mkdir(exist_ok=True)
    (geo_out / "Opstillingskreds-FV2022.json").write_text(
        json.dumps(opstillingskredse, ensure_ascii=False, indent=2)
    )
    (geo_out / "Afstemningsomraade-FV2022.json").write_text(
        json.dumps(all_aos, ensure_ascii=False, indent=2)
    )

    kd_out = wave_dir / "kandidat-data"
    kd_out.mkdir(exist_ok=True)
    for src in kandidat_dir.glob("*.json"):
        if not src.name.endswith(".hash"):
            shutil.copy2(src, kd_out / src.name)


def write_preliminary_wave(
    wave_dir: Path,
    wave_index: int,
    ao_ids_in_wave: list[str],
    hierarchy: dict[str, dict],
    cumulative_ok_votes: dict[str, dict[str, int]],
    fv2022_votes: dict[tuple[str, str], dict[str, int]],
) -> None:
    """Write one preliminary wave: partistemmefordeling (cumulative) + valgdeltagelse."""
    wave_dir.mkdir(parents=True, exist_ok=True)
    t = WAVE_TIMES[wave_index]

    description = wave_description(wave_index, ao_ids_in_wave, hierarchy)
    (wave_dir / "_meta.json").write_text(json.dumps({
        "label": f"{t} — {description}",
        "time": t,
        "interval_s": float(WAVE_INTERVALS[wave_index]),
        "phase": "preliminary",
    }, ensure_ascii=False, indent=2))

    pf_dir = wave_dir / "partistemmefordeling"
    pf_dir.mkdir(exist_ok=True)
    vd_dir = wave_dir / "valgdeltagelse"
    vd_dir.mkdir(exist_ok=True)

    affected_ok_ids: set[str] = set()

    for ao_id in ao_ids_in_wave:
        info = hierarchy[ao_id]
        ok_id = info["ok_id"]
        ok_name = info["ok_name"]
        ao_name = info["ao_name"]
        # Use same normalization as parse_fv2022_csv / build_id_mapping
        key = (normalize_ok_name(ok_name), normalize_ao_name(ao_name))
        ao_party_votes = fv2022_votes.get(key, {})

        ok_votes = cumulative_ok_votes.setdefault(ok_id, {})
        for party_id, votes in ao_party_votes.items():
            ok_votes[party_id] = ok_votes.get(party_id, 0) + votes
        affected_ok_ids.add(ok_id)

        eligible = info.get("eligible_voters", 0)
        total_party_votes = sum(ao_party_votes.values())
        vd_data = {
            "Valgart": "Folketingsvalg",
            "AfstemningsomraadeDagiId": str(ao_id),
            "Valgdeltagelse": [{
                "AntalStemmeberettigede": eligible,
                "AfgivneStemmer": total_party_votes,
                "Tidspunkt": f"{t}:00",
            }],
        }
        (vd_dir / f"valgdeltagelse-{ao_id}.json").write_text(
            json.dumps(vd_data, ensure_ascii=False, indent=2)
        )

    for ok_id in affected_ok_ids:
        pf = build_partistemmefordeling(ok_id, cumulative_ok_votes[ok_id])
        (pf_dir / f"partistemmefordeling-{ok_id}.json").write_text(
            json.dumps(pf, ensure_ascii=False, indent=2)
        )


def write_fintaelling_wave(
    wave_dir: Path,
    wave_index: int,
    ao_ids_in_wave: list[str],
    hierarchy: dict[str, dict],
    fv2022_votes: dict[tuple[str, str], dict[str, int]],
    kandidatdata: dict[str, dict[str, list[dict]]],
) -> None:
    """Write one fintaelling wave: valgresultater with synthetic candidate votes."""
    wave_dir.mkdir(parents=True, exist_ok=True)
    t = WAVE_TIMES[wave_index]

    description = "Fintaelling — " + wave_description(wave_index, ao_ids_in_wave, hierarchy)
    (wave_dir / "_meta.json").write_text(json.dumps({
        "label": f"{t} — {description}",
        "time": t,
        "interval_s": float(WAVE_INTERVALS[wave_index]),
        "phase": "final",
    }, ensure_ascii=False, indent=2))

    vr_dir = wave_dir / "valgresultater"
    vr_dir.mkdir(exist_ok=True)

    for ao_id in ao_ids_in_wave:
        info = hierarchy[ao_id]
        ok_id = info["ok_id"]
        ok_name = info["ok_name"]
        ao_name = info["ao_name"]
        key = (normalize_ok_name(ok_name), normalize_ao_name(ao_name))
        ao_party_votes = fv2022_votes.get(key, {})

        party_data: dict[str, dict] = {}
        for party_id, total in ao_party_votes.items():
            candidates = kandidatdata.get(ok_id, {}).get(party_id, [])
            party_data[party_id] = {
                "total": total,
                "candidates_by_ok": {ok_id: candidates},
            }

        vr = build_valgresultater(
            ao_id=str(ao_id),
            optaellingstype="Fintaelling",
            party_data=party_data,
            ao_ok_id=ok_id,
        )
        safe_ao_name = ao_name.replace("/", "-").replace(" ", "_")[:40]
        filename = f"valgresultater-Folketingsvalg-{safe_ao_name}-{ao_id}.json"
        (vr_dir / filename).write_text(json.dumps(vr, ensure_ascii=False, indent=2))


# ── Main helper functions ──────────────────────────────────────────────────────

def build_storkredse_list(geografi_dir: Path) -> list[dict]:
    """Extract storkredse from geografi files, formatted for Storkreds.json.

    Actual schema: {Nummer, Navn, Valglandsdelkode, Type} — no AntalKredsmandater.
    """
    result = []
    for f in geografi_dir.glob("*.json"):
        if f.name.endswith(".hash"):
            continue
        data = json.loads(f.read_text())
        if isinstance(data, list) and data and data[0].get("Type") == "Storkreds":
            for item in data:
                nummer = item.get("Nummer", item.get("Kode"))
                result.append({
                    "Kode": str(nummer),
                    "Navn": item.get("Navn", ""),
                    "AntalKredsmandater": STORKREDS_KREDSMANDATER.get(nummer, 0),
                    "ValgId": "FV2022",
                })
    return result


def build_opstillingskredse_list(geografi_dir: Path) -> list[dict]:
    """Extract opstillingskredse formatted for Opstillingskreds-FV2022.json.

    Actual schema: {Dagi_id, Nummer, Navn, Storkredskode, Type}.
    """
    result = []
    for f in geografi_dir.glob("*.json"):
        if f.name.endswith(".hash"):
            continue
        data = json.loads(f.read_text())
        if isinstance(data, list) and data and data[0].get("Type") == "Opstillingskreds":
            for item in data:
                result.append({
                    "Kode": str(item.get("Dagi_id", "")),
                    "Navn": item.get("Navn", ""),
                    "StorkredskodeKode": str(item.get("Storkredskode", "")),
                    "ValgId": "FV2022",
                })
    return result


def build_aos_list(hierarchy: dict[str, dict]) -> list[dict]:
    """Build Afstemningsomraade-FV2022.json list from hierarchy."""
    return [
        {
            "Kode": str(ao_id),
            "Navn": info["ao_name"],
            "OpstillingskredsKode": str(info["ok_id"]),
            "AntalStemmeberettigede": info["eligible_voters"],
            "ValgId": "FV2022",
        }
        for ao_id, info in hierarchy.items()
    ]


def build_parties_list() -> list[dict]:
    """Return hardcoded FV2022 party list."""
    return [
        {"Id": "A", "Bogstav": "A", "Navn": "Socialdemokratiet"},
        {"Id": "B", "Bogstav": "B", "Navn": "Radikale Venstre"},
        {"Id": "C", "Bogstav": "C", "Navn": "Det Konservative Folkeparti"},
        {"Id": "D", "Bogstav": "D", "Navn": "Nye Borgerlige"},
        {"Id": "F", "Bogstav": "F", "Navn": "SF — Socialistisk Folkeparti"},
        {"Id": "I", "Bogstav": "I", "Navn": "Liberal Alliance"},
        {"Id": "K", "Bogstav": "K", "Navn": "Kristendemokraterne"},
        {"Id": "M", "Bogstav": "M", "Navn": "Moderaterne"},
        {"Id": "O", "Bogstav": "O", "Navn": "Dansk Folkeparti"},
        {"Id": "Q", "Bogstav": "Q", "Navn": "Frie Gronne"},
        {"Id": "V", "Bogstav": "V", "Navn": "Venstre"},
        {"Id": "Aa", "Bogstav": "Aa", "Navn": "Alternativet"},
        {"Id": "Ae", "Bogstav": "Ae", "Navn": "Danmarksdemokraterne"},
        {"Id": "Oe", "Bogstav": "Oe", "Navn": "Enhedslisten"},
    ]


def wave_description(wave_index: int, ao_ids: list[str], hierarchy: dict[str, dict]) -> str:
    """Generate a human-readable description for a wave's AOs."""
    if wave_index == 1:
        sk_names = list(dict.fromkeys(hierarchy[a]["sk_name"] for a in ao_ids if a in hierarchy))
        return "Oeer — " + ", ".join(sk_names[:4])
    sk_names = list(dict.fromkeys(hierarchy[a]["sk_name"] for a in ao_ids if a in hierarchy))
    return ", ".join(sk_names[:3]) + (f" +{len(sk_names)-3} mere" if len(sk_names) > 3 else "")


def run(force: bool = False) -> None:
    print(f"Building FV2022 scenario -> {OUTPUT_DIR}\n")

    # Phase 1: Download
    download_all(force=force)

    # Phase 2: Parse
    print("Phase 2: Parsing ...")
    geo_dir = CACHE_DIR / "fv2026" / "geografi"
    kd_dir = CACHE_DIR / "fv2026" / "kandidat-data"
    csv_path = CACHE_DIR / "fv2022_results.csv"

    hierarchy = parse_geografi(geo_dir)
    kandidatdata = parse_kandidatdata(kd_dir)
    fv2022_votes = parse_fv2022_csv(csv_path)
    id_mapping = build_id_mapping(hierarchy)

    matched_ao_ids = {id_mapping[k]: hierarchy[id_mapping[k]] for k in fv2022_votes if k in id_mapping}
    unmatched = [k for k in fv2022_votes if k not in id_mapping]
    print(f"  Matched {len(matched_ao_ids)}/{len(fv2022_votes)} AOs "
          f"({100*len(matched_ao_ids)//max(1,len(fv2022_votes))}%)")
    if unmatched:
        print(f"  Unmatched ({len(unmatched)}): {unmatched[:5]} ...")
    print()

    # Phase 3: Wave assignment
    print("Phase 3: Assigning waves ...")
    island_ao_ids = detect_island_ao_ids(matched_ao_ids)
    print(f"  Island AOs -> wave_01: {len(island_ao_ids)}")
    prelim_assignment = assign_preliminary_waves(matched_ao_ids, N_PRELIM_WAVES, island_ao_ids)

    prelim_by_wave: dict[int, list[str]] = {}
    for ao_id, wave_num in prelim_assignment.items():
        prelim_by_wave.setdefault(wave_num, []).append(ao_id)

    # Assign fintaelling waves: spread prelim waves evenly across final wave slots
    final_by_wave: dict[int, list[str]] = {}
    for prelim_wave in sorted(prelim_by_wave.keys()):
        final_wave = N_PRELIM_WAVES + 1 + ((prelim_wave - 1) * N_FINAL_WAVES // N_PRELIM_WAVES)
        final_wave = min(final_wave, 32)
        final_by_wave.setdefault(final_wave, []).extend(prelim_by_wave[prelim_wave])
    print(f"  Preliminary waves: {len(prelim_by_wave)}, Fintaelling waves: {len(final_by_wave)}")
    print()

    # Phase 4: Write output
    print("Phase 4: Writing wave files ...")
    if OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)
    OUTPUT_DIR.mkdir(parents=True)

    storkredse = build_storkredse_list(geo_dir)
    opstillingskredse = build_opstillingskredse_list(geo_dir)
    all_aos = build_aos_list(matched_ao_ids)
    parties = build_parties_list()

    write_wave_00(OUTPUT_DIR, geo_dir, kd_dir, storkredse, opstillingskredse, all_aos, parties)
    print(f"  wave_00: setup ({len(storkredse)} storkredse, {len(opstillingskredse)} ok, {len(all_aos)} AOs)")

    cumulative_ok_votes: dict[str, dict[str, int]] = {}
    for wave_num in range(1, N_PRELIM_WAVES + 1):
        ao_ids = prelim_by_wave.get(wave_num, [])
        if not ao_ids:
            continue
        wave_dir = OUTPUT_DIR / f"wave_{wave_num:02d}"
        write_preliminary_wave(wave_dir, wave_num, ao_ids, matched_ao_ids, cumulative_ok_votes, fv2022_votes)
        print(f"  wave_{wave_num:02d}: {len(ao_ids)} AOs")

    for wave_num in range(N_PRELIM_WAVES + 1, 33):
        ao_ids = final_by_wave.get(wave_num, [])
        if not ao_ids:
            continue
        wave_dir = OUTPUT_DIR / f"wave_{wave_num:02d}"
        write_fintaelling_wave(wave_dir, wave_num, ao_ids, matched_ao_ids, fv2022_votes, kandidatdata)
        print(f"  wave_{wave_num:02d}: fintaelling {len(ao_ids)} AOs")

    print(f"\nDone. {len(list(OUTPUT_DIR.glob('wave_*')))} waves written to {OUTPUT_DIR}")


# ── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    force = "--force" in sys.argv
    run(force=force)
