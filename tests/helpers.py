"""Test helpers for loading FV2022 scenario data."""
from __future__ import annotations

import json
from pathlib import Path

_SCENARIO_DIR = Path(__file__).resolve().parent.parent / "valg" / "scenarios" / "fv2022"

# Party ID normalisation: scenario data uses Æ/Ø/Å, calculator tests use AE/OE/AA
_PARTY_NORM = {"Æ": "AE", "Ø": "OE", "Å": "AA"}


def _norm_party(pid: str) -> str:
    return _PARTY_NORM.get(pid, pid)


def load_fv2022_final_votes():
    """Load final FV2022 vote data from scenario waves.

    Uses partistemmefordeling (OK-level cumulative totals) from the last wave,
    which includes votes from AOs that couldn't be matched to FV2026 geography.

    Returns (national_votes, storkreds_votes, kredsmandater) matching
    the signature of ``allocate_seats_detail``.

    Raises FileNotFoundError if scenario data is missing.
    """
    geo_dir = _SCENARIO_DIR / "wave_00" / "geografi"
    if not geo_dir.exists():
        raise FileNotFoundError(f"FV2022 geography not found at {geo_dir}")

    # Build OK → storkreds mapping
    oks = json.loads((geo_dir / "Opstillingskreds-FV2022.json").read_text())
    ok_to_sk = {ok["Kode"]: ok["StorkredskodeKode"] for ok in oks}

    # Find the latest partistemmefordeling per OK (last wave wins)
    ok_votes: dict[str, dict[str, int]] = {}
    for wave_dir in sorted(_SCENARIO_DIR.glob("wave_*")):
        pf_dir = wave_dir / "partistemmefordeling"
        if not pf_dir.exists():
            continue
        for f in pf_dir.glob("*.json"):
            data = json.loads(f.read_text())
            valg = data.get("Valg", {})
            ok_id = valg.get("OpstillingskredsId", "")
            if not ok_id:
                continue
            parties: dict[str, int] = {}
            for p in valg.get("Partier", []):
                pid = _norm_party(p["PartiId"])
                parties[pid] = p.get("Stemmer", 0)
            ok_votes[ok_id] = parties

    # Aggregate by storkreds
    storkreds_votes: dict[str, dict[str, int]] = {}
    national_votes: dict[str, int] = {}
    for ok_id, parties in ok_votes.items():
        sk = ok_to_sk.get(ok_id, "")
        if not sk:
            continue
        sk_dict = storkreds_votes.setdefault(sk, {})
        for pid, v in parties.items():
            sk_dict[pid] = sk_dict.get(pid, 0) + v
            national_votes[pid] = national_votes.get(pid, 0) + v

    kredsmandater = {
        "1": 18, "2": 12, "3": 9, "4": 2, "5": 18,
        "6": 12, "7": 19, "8": 16, "9": 16, "10": 13,
    }

    return national_votes, storkreds_votes, kredsmandater
