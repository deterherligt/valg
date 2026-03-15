"""Tests for KV2025 → FV transformation functions."""
import pytest
from valg.scenarios.kv2025_transform import (
    FT_PARTY_LETTERS,
    filter_ft_lists,
    build_party_registry,
    transform_storkreds_json,
    transform_geography_files,
    assign_candidates_to_ok,
    transform_kandidatdata_json,
    transform_valgresultater_preliminary,
    transform_valgresultater_final,
    aggregate_partistemmer,
    bucket_aos,
)


# ── filter_ft_lists ─────────────────────────────────────────────────────────

def test_filter_ft_lists_keeps_ft_parties():
    lists = [
        {"Bogstavbetegnelse": "A", "Stemmer": 100, "Kandidater": []},
        {"Bogstavbetegnelse": "L", "Stemmer": 50, "Kandidater": []},  # local
        {"Bogstavbetegnelse": "V", "Stemmer": 200, "Kandidater": []},
    ]
    result = filter_ft_lists(lists)
    assert len(result) == 2
    assert {r["Bogstavbetegnelse"] for r in result} == {"A", "V"}


def test_filter_ft_lists_empty():
    assert filter_ft_lists([]) == []


def test_filter_ft_lists_all_local():
    lists = [{"Bogstavbetegnelse": "G", "Stemmer": 10, "Kandidater": []}]
    assert filter_ft_lists(lists) == []


# ── build_party_registry ─────────────────────────────────────────────────────

def test_build_party_registry_first_occurrence_wins():
    """First name seen for each letter is canonical."""
    results_by_kommune = [
        [  # Aabenraa
            {"Bogstavbetegnelse": "A", "Navn": "Socialdemokratiet", "KandidatlisteId": "x"},
            {"Bogstavbetegnelse": "L", "Navn": "Lokal Liste", "KandidatlisteId": "y"},
        ],
        [  # Aalborg — A appears again with different name
            {"Bogstavbetegnelse": "A", "Navn": "Socialdemokraterne", "KandidatlisteId": "z"},
            {"Bogstavbetegnelse": "V", "Navn": "Venstre", "KandidatlisteId": "w"},
        ],
    ]
    registry = build_party_registry(results_by_kommune)
    assert registry["A"] == "Socialdemokratiet"  # first occurrence wins
    assert registry["V"] == "Venstre"
    assert "L" not in registry  # local list filtered out


def test_build_party_registry_empty():
    assert build_party_registry([]) == {}


# ── transform_storkreds_json ─────────────────────────────────────────────────

def test_transform_storkreds_json():
    kommuner = [
        {"Kode": 101, "Navn": "København"},
        {"Kode": 851, "Navn": "Aalborg"},
    ]
    mandatfordeling = {101: 55, 851: 31}
    result = transform_storkreds_json(kommuner, mandatfordeling)
    assert len(result) == 2
    kbh = next(r for r in result if r["Kode"] == "101")
    assert kbh["Navn"] == "København"
    assert kbh["AntalKredsmandater"] == 55
    assert kbh["ValgId"] == "KV2025"


def test_transform_storkreds_json_missing_mandatfordeling():
    """Komuner without mandatfordeling entry get a default of 0."""
    kommuner = [{"Kode": 999, "Navn": "Unknown"}]
    result = transform_storkreds_json(kommuner, {})
    assert result[0]["AntalKredsmandater"] == 0


# ── transform_geography_files ────────────────────────────────────────────────

def test_transform_geography_files_keys():
    kommuner = [{"Kode": 101, "Navn": "København", "Dagi_id": "111"}]
    opstillingskredse = [{"Kode": 10101, "Navn": "Bispebjerg", "KommuneKode": 101, "Dagi_id": "222"}]
    aos = [{"Dagi_id": "333", "Nummer": 1, "Navn": "Bispebjerg Skole",
            "OpstillingskredsKode": 10101, "StemmeberettigeteVaelgere": 2500}]
    result = transform_geography_files(kommuner, opstillingskredse, aos)
    assert "Opstillingskreds" in result
    assert "Afstemningsomraade" in result
    ok = result["Opstillingskreds"][0]
    assert ok["Kode"] == "10101"
    assert ok["Navn"] == "Bispebjerg"
    assert ok["StorkredskodeKode"] == "101"  # parent kommune as storkreds
    ao = result["Afstemningsomraade"][0]
    assert ao["Kode"] == "333"
    assert ao["OpstillingskredsKode"] == "10101"
    assert ao["AntalStemmeberettigede"] == 2500


# ── assign_candidates_to_ok ──────────────────────────────────────────────────

def test_assign_candidates_to_ok_uses_largest():
    """All candidates for a party in a kommune go to the largest opstillingskreds."""
    ok_by_voters = {
        "10101": 500,
        "10102": 2000,  # largest
        "10103": 800,
    }
    kommune_kode = 101
    ok_kode_to_storkreds = {"10101": "101", "10102": "101", "10103": "101"}
    kandidater = [
        {"Id": "c1", "Stemmeseddelnavn": "Anne Larsen, København", "Nummer": 1},
        {"Id": "c2", "Stemmeseddelnavn": "Bo Mikkelsen, København", "Nummer": 2},
    ]
    result = assign_candidates_to_ok(kandidater, "A", kommune_kode, ok_by_voters, ok_kode_to_storkreds)
    assert all(r["ok_id"] == "10102" for r in result)
    assert all(r["party_letter"] == "A" for r in result)
    assert result[0]["id"] == "c1"
    assert result[1]["ballot_position"] == 2


# ── transform_kandidatdata_json ───────────────────────────────────────────────

def test_transform_kandidatdata_json_structure():
    party_registry = {"A": "Socialdemokratiet", "V": "Venstre"}
    candidates = [
        {"id": "c1", "name": "Anne Larsen", "party_letter": "A",
         "ok_id": "10101", "ballot_position": 1},
        {"id": "c2", "name": "Bo Mikkelsen", "party_letter": "V",
         "ok_id": "10101", "ballot_position": 1},
    ]
    result = transform_kandidatdata_json(party_registry, candidates)
    assert result["Valg"]["Id"] == "KV2025"
    parties = result["Valg"]["IndenforParti"]
    a_entry = next(p for p in parties if p["Id"] == "A")
    assert len(a_entry["Kandidater"]) == 1
    assert a_entry["Kandidater"][0]["Id"] == "c1"
    assert a_entry["Kandidater"][0]["Stemmeseddelplacering"] == 1


# ── transform_valgresultater_preliminary ─────────────────────────────────────

def test_transform_valgresultater_preliminary():
    party_registry = {"A": "Socialdemokratiet", "V": "Venstre"}
    ao_result = {
        "AfstemningsomraadeDagiId": "333",
        "Kandidatlister": [
            {"Bogstavbetegnelse": "A", "Navn": "Socialdemokratiet",
             "KandidatlisteId": "x", "Stemmer": 150, "Listestemmer": 30,
             "Kandidater": [{"Id": "c1", "Stemmeseddelnavn": "Anne", "Stemmer": 120}]},
            {"Bogstavbetegnelse": "L", "Navn": "Lokal", "KandidatlisteId": "y",
             "Stemmer": 20, "Listestemmer": 20, "Kandidater": []},
        ],
    }
    result = transform_valgresultater_preliminary(ao_result, party_registry)
    vr = result["Valgresultater"]
    assert vr["AfstemningsomraadeId"] == "333"
    assert vr["Optaellingstype"] == "Foreløbig"
    assert len(vr["IndenforParti"]) == 1  # only A, L filtered out
    party = vr["IndenforParti"][0]
    assert party["PartiId"] == "A"
    assert party["Partistemmer"] == 150
    assert party["Kandidater"] == []  # no candidates in preliminary


def test_transform_valgresultater_preliminary_all_local():
    party_registry = {"V": "Venstre"}
    ao_result = {
        "AfstemningsomraadeDagiId": "333",
        "Kandidatlister": [
            {"Bogstavbetegnelse": "L", "Navn": "Lokal", "KandidatlisteId": "y",
             "Stemmer": 20, "Listestemmer": 20, "Kandidater": []},
        ],
    }
    result = transform_valgresultater_preliminary(ao_result, party_registry)
    assert result["Valgresultater"]["IndenforParti"] == []


# ── transform_valgresultater_final ───────────────────────────────────────────

def test_transform_valgresultater_final():
    party_registry = {"A": "Socialdemokratiet"}
    ao_result = {
        "AfstemningsomraadeDagiId": "333",
        "Kandidatlister": [
            {"Bogstavbetegnelse": "A", "Navn": "Socialdemokratiet",
             "KandidatlisteId": "x", "Stemmer": 150, "Listestemmer": 30,
             "Kandidater": [
                 {"Id": "c1", "Stemmeseddelnavn": "Anne", "Stemmer": 120},
                 {"Id": "c2", "Stemmeseddelnavn": "Bo", "Stemmer": 30},
             ]},
        ],
    }
    result = transform_valgresultater_final(ao_result, party_registry)
    vr = result["Valgresultater"]
    assert vr["Optaellingstype"] == "Fintaelling"
    party = vr["IndenforParti"][0]
    assert len(party["Kandidater"]) == 2
    assert party["Kandidater"][0] == {"KandidatId": "c1", "Stemmer": 120}


# ── aggregate_partistemmer ───────────────────────────────────────────────────

def test_aggregate_partistemmer():
    """Sums Stemmer per party per opstillingskreds across AOs."""
    party_registry = {"A": "Socialdemokratiet", "V": "Venstre"}
    ao_results = [
        {
            "AfstemningsomraadeDagiId": "ao1",
            "Kandidatlister": [
                {"Bogstavbetegnelse": "A", "KandidatlisteId": "x", "Stemmer": 100, "Listestemmer": 20, "Kandidater": []},
            ],
        },
        {
            "AfstemningsomraadeDagiId": "ao2",
            "Kandidatlister": [
                {"Bogstavbetegnelse": "A", "KandidatlisteId": "x", "Stemmer": 80, "Listestemmer": 10, "Kandidater": []},
                {"Bogstavbetegnelse": "V", "KandidatlisteId": "y", "Stemmer": 50, "Listestemmer": 50, "Kandidater": []},
            ],
        },
    ]
    ao_to_ok = {"ao1": "ok1", "ao2": "ok1"}
    result = aggregate_partistemmer(ao_results, party_registry, ao_to_ok)
    assert "ok1" in result
    ok1 = result["ok1"]
    assert ok1["Valg"]["OpstillingskredsId"] == "ok1"
    parties = {p["PartiId"]: p["Stemmer"] for p in ok1["Valg"]["Partier"]}
    assert parties["A"] == 180  # 100 + 80
    assert parties["V"] == 50


# ── bucket_aos ───────────────────────────────────────────────────────────────

def test_bucket_aos_sorted_ascending():
    """AOs are sorted by eligible_voters and split at thresholds."""
    aos = [
        {"id": "a", "eligible_voters": 3000},
        {"id": "b", "eligible_voters": 200},
        {"id": "c", "eligible_voters": 800},
        {"id": "d", "eligible_voters": 8000},
        {"id": "e", "eligible_voters": 1200},
    ]
    thresholds = [500, 1000, 5000]
    buckets = bucket_aos(aos, thresholds)
    assert len(buckets) == 4
    assert [x["id"] for x in buckets[0]] == ["b"]
    assert [x["id"] for x in buckets[1]] == ["c"]
    assert [x["id"] for x in buckets[2]] == ["e", "a"]
    assert [x["id"] for x in buckets[3]] == ["d"]


def test_bucket_aos_empty_bucket_excluded():
    """Empty buckets (no AOs in range) are omitted."""
    aos = [
        {"id": "a", "eligible_voters": 200},
        {"id": "b", "eligible_voters": 8000},
    ]
    thresholds = [500, 1000, 5000]
    buckets = bucket_aos(aos, thresholds)
    assert len(buckets) == 2
    assert buckets[0][0]["id"] == "a"
    assert buckets[1][0]["id"] == "b"
