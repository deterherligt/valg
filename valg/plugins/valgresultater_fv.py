from __future__ import annotations
# valg/plugins/valgresultater_fv.py
TABLE = "results"

_LETTER_MAP = {"Æ": "Ae", "Ø": "Oe", "Å": "Aa"}

def MATCH(filename: str) -> bool:
    return filename.startswith("valgresultater-Folketingsvalg")

def parse(data: dict | list, snapshot_at: str) -> list[dict]:
    rows = []
    if not isinstance(data, dict):
        return []

    # 2026 format: flat dict with AfstemningsområdeDagiId
    # FV2022 format: {"Valgresultater": {"AfstemningsomraadeId": ..., ...}}
    vr = data.get("Valgresultater")
    if vr and isinstance(vr, dict):
        ao_id = str(vr.get("AfstemningsomraadeId", ""))
        raw_type = (vr.get("Optaellingstype") or "").lower()
        parties = vr.get("IndenforParti") or []
        udenfor = vr.get("KandidaterUdenforParti") or []
        get_party_id = lambda p: p.get("PartiId") or ""
        get_cand_id = lambda k: k.get("KandidatId")
        get_party_votes = lambda p: p.get("Partistemmer")
    else:
        ao_id = str(data.get("AfstemningsområdeDagiId") or data.get("AfstemningsomraadeDagiId") or "")
        raw_type = (data.get("Resultatart") or "").lower()
        parties = data.get("IndenforParti") or []
        udenfor = []
        get_party_id = lambda p: _LETTER_MAP.get(p.get("Bogstavbetegnelse") or "", p.get("Bogstavbetegnelse") or "")
        get_cand_id = lambda k: k.get("Id")
        get_party_votes = lambda p: p.get("Stemmer")

    if "ingenresultater" in raw_type or "ingen" in raw_type:
        return []
    if "endelig" in raw_type or "final" in raw_type or "fintaelling" in raw_type or "fintælling" in raw_type:
        count_type = "final"
    elif "foreløbig" in raw_type or "prelim" in raw_type:
        count_type = "preliminary"
    else:
        count_type = "preliminary"

    for party in parties:
        party_id = get_party_id(party)
        pv = get_party_votes(party)
        if pv is not None:
            rows.append({
                "afstemningsomraade_id": ao_id,
                "party_id": party_id,
                "candidate_id": None,
                "votes": pv,
                "count_type": count_type,
                "snapshot_at": snapshot_at,
            })
        for k in (party.get("Kandidater") or []):
            rows.append({
                "afstemningsomraade_id": ao_id,
                "party_id": party_id,
                "candidate_id": get_cand_id(k),
                "votes": k.get("Stemmer"),
                "count_type": count_type,
                "snapshot_at": snapshot_at,
            })

    for k in udenfor:
        rows.append({
            "afstemningsomraade_id": ao_id,
            "party_id": None,
            "candidate_id": get_cand_id(k),
            "votes": k.get("Stemmer"),
            "count_type": count_type,
            "snapshot_at": snapshot_at,
        })

    return [r for r in rows if r.get("afstemningsomraade_id") and r.get("votes") is not None]
