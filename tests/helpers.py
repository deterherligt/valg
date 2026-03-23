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

    Returns (national_votes, storkreds_votes, kredsmandater) matching
    the signature of ``allocate_seats_detail``.

    Raises FileNotFoundError if scenario data is missing.
    """
    geo_dir = _SCENARIO_DIR / "wave_00" / "geografi"
    if not geo_dir.exists():
        raise FileNotFoundError(f"FV2022 geography not found at {geo_dir}")

    # Build AO → storkreds mapping
    oks = json.loads((geo_dir / "Opstillingskreds-FV2022.json").read_text())
    ok_to_sk = {ok["Kode"]: ok["StorkredskodeKode"] for ok in oks}

    aos = json.loads((geo_dir / "Afstemningsomraade-FV2022.json").read_text())
    ao_to_sk = {}
    for ao in aos:
        ok_id = ao["OpstillingskredsKode"]
        ao_to_sk[ao["Kode"]] = ok_to_sk.get(ok_id, "")

    # Collect latest valgresultater per AO (later waves overwrite earlier)
    ao_votes: dict[str, dict[str, int]] = {}
    for wave_dir in sorted(_SCENARIO_DIR.glob("wave_*")):
        vr_dir = wave_dir / "valgresultater"
        if not vr_dir.exists():
            continue
        for f in vr_dir.glob("*.json"):
            data = json.loads(f.read_text())
            vr = data.get("Valgresultater", {})
            ao_id = vr.get("AfstemningsomraadeId", "")
            if not ao_id:
                continue
            parties: dict[str, int] = {}
            for p in vr.get("IndenforParti", []):
                pid = _norm_party(p["PartiId"])
                party_list = p.get("Partistemmer", 0)
                personal = sum(c.get("Stemmer", 0) for c in p.get("Kandidater", []))
                parties[pid] = party_list + personal
            ao_votes[ao_id] = parties

    # Aggregate by storkreds
    storkreds_votes: dict[str, dict[str, int]] = {}
    national_votes: dict[str, int] = {}
    for ao_id, parties in ao_votes.items():
        sk = ao_to_sk.get(ao_id, "")
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
