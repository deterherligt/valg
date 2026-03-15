"""
Pure transformation functions: KV2025 (kommunalvalg) → FV (folketingsvalg) format.

No I/O. All functions take parsed dicts and return serialisable dicts/lists.
Election ID used throughout: KV2025
"""
from __future__ import annotations

FT_PARTY_LETTERS: frozenset[str] = frozenset(
    {"A", "B", "C", "D", "F", "I", "M", "O", "V", "Ø", "Å"}
)

_ELECTION_ID = "KV2025"


def filter_ft_lists(kandidatlister: list[dict]) -> list[dict]:
    """Keep only lists whose Bogstavbetegnelse is a national FT party letter."""
    return [k for k in kandidatlister if k.get("Bogstavbetegnelse") in FT_PARTY_LETTERS]


def build_party_registry(results_by_kommune: list[list[dict]]) -> dict[str, str]:
    """
    Return {letter: name} for all FT parties found across all kommuner.
    First occurrence of each letter wins.

    Each element in results_by_kommune is the list of Kandidatlister for one kommune
    (from valgresultater or kandidat-data files).
    """
    registry: dict[str, str] = {}
    for lists in results_by_kommune:
        for kl in lists:
            letter = kl.get("Bogstavbetegnelse", "")
            if letter in FT_PARTY_LETTERS and letter not in registry:
                registry[letter] = kl.get("Navn", letter)
    return registry


def transform_storkreds_json(
    kommuner: list[dict],
    mandatfordeling: dict[int, int],
) -> list[dict]:
    """
    Return a list of FV-format storkreds dicts (content of Storkreds.json).

    kommuner: list of Kommune dicts from SFTP geografi/Kommune-*.json
    mandatfordeling: {kommune_kode: byraadssize}
    """
    total_seats = sum(mandatfordeling.values()) or 1
    return [
        {
            "Kode": str(k["Kode"]),
            "Navn": k["Navn"],
            "AntalKredsmandater": max(1, round(mandatfordeling.get(k["Kode"], 0) / total_seats * 135)),
            "ValgId": _ELECTION_ID,
        }
        for k in kommuner
    ]


def transform_geography_files(
    opstillingskredse: list[dict],
    afstemningsomraader: list[dict],
) -> dict[str, list[dict]]:
    """
    Return FV-format geography dicts for Opstillingskreds and Afstemningsomraade files.

    Returns:
        {
            "Opstillingskreds": [...],
            "Afstemningsomraade": [...],
        }
    """
    ok_list = [
        {
            "Kode": str(ok["Kode"]),
            "Navn": ok["Navn"],
            "StorkredskodeKode": str(ok["KommuneKode"]),
            "ValgId": _ELECTION_ID,
        }
        for ok in opstillingskredse
    ]
    ao_list = [
        {
            "Kode": ao["Dagi_id"],
            "Navn": ao["Navn"],
            "OpstillingskredsKode": str(ao["OpstillingskredsKode"]),
            "AntalStemmeberettigede": ao.get("StemmeberettigeteVaelgere", 0),
            "ValgId": _ELECTION_ID,
        }
        for ao in afstemningsomraader
    ]
    return {"Opstillingskreds": ok_list, "Afstemningsomraade": ao_list}


def assign_candidates_to_ok(
    kandidater: list[dict],
    party_letter: str,
    kommune_kode: int,
    ok_by_voters: dict[str, int],
    ok_kode_to_storkreds: dict[str, str],
) -> list[dict]:
    """
    Assign all candidates for a party list in a kommune to the largest opstillingskreds
    (by eligible voters) in that kommune.

    Returns list of candidate dicts with fields: id, name, party_letter, ok_id,
    ballot_position.
    """
    kommune_oks = [k for k in ok_by_voters if ok_kode_to_storkreds.get(k) == str(kommune_kode)]
    if not kommune_oks:
        return []
    target_ok = max(kommune_oks, key=lambda k: ok_by_voters[k])
    return [
        {
            "id": c["Id"],
            "name": c.get("Stemmeseddelnavn", c.get("Navn", "")),
            "party_letter": party_letter,
            "ok_id": target_ok,
            "ballot_position": c.get("Nummer", i + 1),
        }
        for i, c in enumerate(kandidater)
    ]


def transform_kandidatdata_json(
    party_registry: dict[str, str],
    candidates: list[dict],
) -> dict:
    """
    Return FV-format kandidat-data dict (content of kandidat-data-Folketingsvalg-KV2025.json).

    candidates: list of dicts with keys: id, name, party_letter, ok_id, ballot_position
    """
    by_party: dict[str, list] = {}
    for c in candidates:
        letter = c.get("party_letter", "")
        if letter in party_registry:
            by_party.setdefault(letter, []).append(c)
    return {
        "Valg": {
            "Id": _ELECTION_ID,
            "IndenforParti": [
                {
                    "Id": letter,
                    "Kandidater": [
                        {
                            "Id": c["id"],
                            "Navn": c["name"],
                            "Stemmeseddelplacering": c.get("ballot_position", 1),
                        }
                        for c in cands
                    ],
                }
                for letter, cands in by_party.items()
            ],
            "UdenforParti": {"Kandidater": []},
        }
    }


def transform_valgresultater_preliminary(
    ao_result: dict,
    party_registry: dict[str, str],
) -> dict:
    """
    Return FV-format preliminary valgresultater dict (Foreløbig, no candidate votes).

    ao_result: one entry from valgresultater SFTP file (has AfstemningsomraadeDagiId,
               Kandidatlister)
    """
    ft_lists = [kl for kl in filter_ft_lists(ao_result.get("Kandidatlister", []))
                if kl["Bogstavbetegnelse"] in party_registry]
    return {
        "Valgresultater": {
            "AfstemningsomraadeId": ao_result["AfstemningsomraadeDagiId"],
            "Optaellingstype": "Foreløbig",
            "IndenforParti": [
                {
                    "PartiId": kl["Bogstavbetegnelse"],
                    "Partistemmer": kl.get("Stemmer", 0),
                    "Kandidater": [],
                }
                for kl in ft_lists
            ],
            "KandidaterUdenforParti": [],
        }
    }


def transform_valgresultater_final(
    ao_result: dict,
    party_registry: dict[str, str],
) -> dict:
    """
    Return FV-format final valgresultater dict (Fintaelling, with candidate votes).
    """
    ft_lists = [kl for kl in filter_ft_lists(ao_result.get("Kandidatlister", []))
                if kl["Bogstavbetegnelse"] in party_registry]
    return {
        "Valgresultater": {
            "AfstemningsomraadeId": ao_result["AfstemningsomraadeDagiId"],
            "Optaellingstype": "Fintaelling",
            "IndenforParti": [
                {
                    "PartiId": kl["Bogstavbetegnelse"],
                    "Partistemmer": kl.get("Stemmer", 0),
                    "Kandidater": [
                        {"KandidatId": c["Id"], "Stemmer": c.get("Stemmer", 0)}
                        for c in kl.get("Kandidater", [])
                    ],
                }
                for kl in ft_lists
            ],
            "KandidaterUdenforParti": [],
        }
    }


def aggregate_partistemmer(
    ao_results: list[dict],
    party_registry: dict[str, str],
    ao_to_ok: dict[str, str],
) -> dict[str, dict]:
    """
    Aggregate party votes per opstillingskreds from ALL ao_results seen so far
    (cumulative, not just the current wave's batch).

    Callers must pass the full accumulated list of AO results up to the current
    wave — not just the current wave's new AOs. This mirrors how real
    partistemmefordeling files are overwritten each sync with the running total.

    Returns {ok_id: partistemmefordeling_data} — one entry per opstillingskreds
    that has at least one reported AO in ao_results.
    """
    totals: dict[str, dict[str, int]] = {}  # ok_id -> {letter: votes}
    for ao in ao_results:
        ao_id = ao["AfstemningsomraadeDagiId"]
        ok_id = ao_to_ok.get(ao_id)
        if ok_id is None:
            continue
        for kl in filter_ft_lists(ao.get("Kandidatlister", [])):
            letter = kl["Bogstavbetegnelse"]
            totals.setdefault(ok_id, {}).setdefault(letter, 0)
            totals[ok_id][letter] += kl.get("Stemmer", 0)

    result = {}
    for ok_id, party_totals in totals.items():
        result[ok_id] = {
            "Valg": {
                "OpstillingskredsId": ok_id,
                "Partier": [
                    {"PartiId": letter, "Stemmer": votes}
                    for letter, votes in party_totals.items()
                ],
            }
        }
    return result


def bucket_aos(
    aos: list[dict],
    thresholds: list[int],
) -> list[list[dict]]:
    """
    Sort AOs by eligible_voters ascending, split into buckets at voter-count thresholds.
    Empty buckets are omitted.

    thresholds: e.g. [500, 1000, 1500, ...] defines N+1 buckets.
    """
    sorted_aos = sorted(aos, key=lambda a: a.get("eligible_voters", 0))
    buckets: list[list[dict]] = []
    prev = 0
    for threshold in thresholds:
        bucket = [a for a in sorted_aos
                  if prev <= a.get("eligible_voters", 0) < threshold]
        if bucket:
            buckets.append(bucket)
        prev = threshold
    # Final bucket: >= last threshold
    final = [a for a in sorted_aos if a.get("eligible_voters", 0) >= prev]
    if final:
        buckets.append(final)
    return buckets
