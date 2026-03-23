# tests/test_plugins.py
import json
import pytest
from pathlib import Path
from valg.plugins import load_plugins, find_plugin

FIXTURES = Path(__file__).parent / "fixtures"

@pytest.fixture(autouse=True)
def plugins():
    load_plugins()


# --- MATCH functions ---

def test_geografi_matches_storkreds_prefix():
    assert find_plugin("Storkreds-test.json") is not None

def test_geografi_matches_storkreds():
    assert find_plugin("Storkreds.json") is not None

def test_kandidatdata_matches_fv():
    assert find_plugin("kandidat-data-Folketingsvalg-Kobenhavn-2024.json") is not None

def test_valgresultater_matches_fv():
    assert find_plugin("valgresultater-Folketingsvalg-Lyngby-Arenaskolen-190820220938.json") is not None

def test_valgdeltagelse_matches():
    assert find_plugin("valgdeltagelse-Lyngby-ArenaskolenAfstS12-190820220938.json") is not None

def test_partistemmer_matches():
    assert find_plugin("partistemmefordeling-Kobenhavn-Opstillingskreds-2024.json") is not None

def test_unknown_file_returns_none():
    assert find_plugin("some-random-file.json") is None


# --- parse functions: geografi ---

def test_geografi_parse_returns_storkredse_rows():
    plugin = find_plugin("Storkreds-test.json")
    data = json.loads((FIXTURES / "geografi_region.json").read_text())
    rows = plugin.parse(data, "2024-11-05T21:00:00")
    assert len(rows) == 2
    assert all("id" in r and "name" in r for r in rows)

def test_geografi_parse_id_is_str_of_nummer():
    plugin = find_plugin("Storkreds-test.json")
    data = json.loads((FIXTURES / "geografi_region.json").read_text())
    rows = plugin.parse(data, "2024-11-05T21:00:00")
    assert rows[0]["id"] == "1"
    assert rows[1]["id"] == "2"

def test_geografi_storkreds_parse():
    plugin = find_plugin("Storkreds.json")
    data = json.loads((FIXTURES / "geografi_storkreds.json").read_text())
    rows = plugin.parse(data, "2024-11-05T21:00:00")
    assert len(rows) == 1


# --- parse functions: valgresultater ---

def test_valgresultater_parse_preliminary_returns_results():
    plugin = find_plugin("valgresultater-Folketingsvalg-Lyngby-Arenaskolen-190820220938.json")
    data = json.loads((FIXTURES / "valgresultater_fv_preliminary.json").read_text())
    rows = plugin.parse(data, "2024-11-05T21:00:00")
    assert len(rows) > 0
    assert all("afstemningsomraade_id" in r for r in rows)
    assert all("votes" in r for r in rows)

def test_valgresultater_parse_sets_count_type_preliminary():
    plugin = find_plugin("valgresultater-Folketingsvalg-Lyngby-Arenaskolen-190820220938.json")
    data = json.loads((FIXTURES / "valgresultater_fv_preliminary.json").read_text())
    rows = plugin.parse(data, "2024-11-05T21:00:00")
    assert all(r["count_type"] == "preliminary" for r in rows)

def test_valgresultater_parse_sets_count_type_final():
    plugin = find_plugin("valgresultater-Folketingsvalg-Lyngby-Arenaskolen-190820220938.json")
    data = json.loads((FIXTURES / "valgresultater_fv_final.json").read_text())
    rows = plugin.parse(data, "2024-11-06T10:00:00")
    assert all(r["count_type"] == "final" for r in rows)

def test_valgresultater_parse_includes_snapshot_at():
    plugin = find_plugin("valgresultater-Folketingsvalg-Lyngby-Arenaskolen-190820220938.json")
    data = json.loads((FIXTURES / "valgresultater_fv_preliminary.json").read_text())
    rows = plugin.parse(data, "2024-11-05T21:00:00")
    assert all(r["snapshot_at"] == "2024-11-05T21:00:00" for r in rows)


# --- parse functions: valgdeltagelse ---

def test_valgdeltagelse_parse_returns_turnout_rows():
    plugin = find_plugin("valgdeltagelse-Lyngby-ArenaskolenAfstS12-190820220938.json")
    data = json.loads((FIXTURES / "valgdeltagelse_fv.json").read_text())
    rows = plugin.parse(data, "2024-11-05T20:00:00")
    assert len(rows) == 1
    assert rows[0]["afstemningsomraade_id"] == "AO1"
    assert rows[0]["votes_cast"] == 1500
    assert rows[0]["eligible_voters"] == 2000


# --- parse functions: partistemmer ---

def test_partistemmer_parse_returns_party_votes_rows():
    plugin = find_plugin("partistemmefordeling-Kobenhavn-Opstillingskreds-2024.json")
    data = json.loads((FIXTURES / "partistemmer_fv.json").read_text())
    rows = plugin.parse(data, "2024-11-05T21:00:00")
    assert len(rows) == 2
    assert all("party_id" in r and "votes" in r for r in rows)
    assert all(r["opstillingskreds_id"] == "OK1" for r in rows)


# --- kandidatdata ---

def test_kandidatdata_parse_returns_candidate_rows():
    plugin = find_plugin("kandidat-data-Folketingsvalg-Kobenhavn-2024.json")
    data = json.loads((FIXTURES / "kandidatdata_fv.json").read_text())
    rows = plugin.parse(data, "2024-11-05T21:00:00")
    assert len(rows) >= 1
    assert any(r.get("name") == "Mette Frederiksen" for r in rows)

def test_geografi_parse_includes_election_id():
    plugin = find_plugin("Storkreds-test.json")
    data = json.loads((FIXTURES / "geografi_region.json").read_text())
    rows = plugin.parse(data, "2024-11-05T21:00:00")
    assert all("election_id" in r for r in rows)

def test_valgresultater_party_row_has_candidate_id_none():
    plugin = find_plugin("valgresultater-Folketingsvalg-Lyngby-Arenaskolen-190820220938.json")
    data = json.loads((FIXTURES / "valgresultater_fv_preliminary.json").read_text())
    rows = plugin.parse(data, "2024-11-05T21:00:00")
    party_rows = [r for r in rows if r.get("candidate_id") is None]
    assert len(party_rows) > 0

def test_valgresultater_candidate_row_has_candidate_id_set():
    plugin = find_plugin("valgresultater-Folketingsvalg-Lyngby-Arenaskolen-190820220938.json")
    data = json.loads((FIXTURES / "valgresultater_fv_preliminary.json").read_text())
    rows = plugin.parse(data, "2024-11-05T21:00:00")
    candidate_rows = [r for r in rows if r.get("candidate_id") is not None]
    assert len(candidate_rows) > 0
    assert all(isinstance(r["candidate_id"], str) for r in candidate_rows)

def test_kandidatdata_parse_includes_ballot_position():
    plugin = find_plugin("kandidat-data-Folketingsvalg-Kobenhavn-2024.json")
    data = json.loads((FIXTURES / "kandidatdata_fv.json").read_text())
    rows = plugin.parse(data, "2024-11-05T21:00:00")
    mette = next(r for r in rows if r.get("name") == "Mette Frederiksen")
    assert mette["ballot_position"] == 1

def test_valgdeltagelse_parse_includes_snapshot_at():
    plugin = find_plugin("valgdeltagelse-Lyngby-ArenaskolenAfstS12-190820220938.json")
    data = json.loads((FIXTURES / "valgdeltagelse_fv.json").read_text())
    rows = plugin.parse(data, "2024-11-05T20:00:00")
    assert all(r["snapshot_at"] == "2024-11-05T20:00:00" for r in rows)


# --- MATCH: new KV2025 plugins ---

def test_parti_matches():
    assert find_plugin("Parti-KV2025.json") is not None

def test_geografi_ao_matches():
    assert find_plugin("Afstemningsomraade-KV2025.json") is not None

def test_geografi_ok_matches():
    assert find_plugin("Opstillingskreds-KV2025.json") is not None


# --- parse functions: parti ---

def test_parti_parse_returns_party_rows():
    plugin = find_plugin("Parti-KV2025.json")
    data = [
        {"Id": "A", "Bogstav": "A", "Navn": "Socialdemokratiet"},
        {"Id": "V", "Bogstav": "V", "Navn": "Venstre"},
    ]
    rows = plugin.parse(data, "2025-11-18T21:00:00")
    assert len(rows) == 2
    assert rows[0] == {"id": "A", "letter": "A", "name": "Socialdemokratiet"}
    assert rows[1] == {"id": "V", "letter": "V", "name": "Venstre"}

def test_parti_parse_skips_missing_id():
    plugin = find_plugin("Parti-KV2025.json")
    data = [
        {"Bogstav": "A", "Navn": "Socialdemokratiet"},
        {"Id": "V", "Bogstav": "V", "Navn": "Venstre"},
    ]
    rows = plugin.parse(data, "2025-11-18T21:00:00")
    assert len(rows) == 1
    assert rows[0]["id"] == "V"

def test_parti_parse_non_list_returns_empty():
    plugin = find_plugin("Parti-KV2025.json")
    assert plugin.parse({}, "2025-11-18T21:00:00") == []


# --- parse functions: geografi_ao ---

def test_geografi_ao_parse_returns_rows():
    plugin = find_plugin("Afstemningsomraade-KV2025.json")
    data = [
        {"Dagi_id": "AO001", "Navn": "Valsted Skole", "Opstillingskreds_Dagi_id": "OK1"},
        {"Dagi_id": "AO002", "Navn": "Biblioteket", "Opstillingskreds_Dagi_id": "OK1"},
    ]
    rows = plugin.parse(data, "2025-11-18T21:00:00")
    assert len(rows) == 2
    assert rows[0]["id"] == "AO001"
    assert rows[0]["name"] == "Valsted Skole"
    assert rows[0]["opstillingskreds_id"] == "OK1"

def test_geografi_ao_parse_skips_missing_id():
    plugin = find_plugin("Afstemningsomraade-KV2025.json")
    data = [
        {"Navn": "Skole uden kode", "Opstillingskreds_Dagi_id": "OK1"},
        {"Dagi_id": "AO002", "Navn": "OK skole", "Opstillingskreds_Dagi_id": "OK1"},
    ]
    rows = plugin.parse(data, "2025-11-18T21:00:00")
    assert len(rows) == 1
    assert rows[0]["id"] == "AO002"

def test_geografi_ao_parse_non_list_returns_empty():
    plugin = find_plugin("Afstemningsomraade-KV2025.json")
    assert plugin.parse({}, "2025-11-18T21:00:00") == []


# --- parse functions: geografi_ok ---

def test_geografi_ok_parse_returns_rows():
    plugin = find_plugin("Opstillingskreds-KV2025.json")
    data = [
        {"Dagi_id": "OK1", "Navn": "Kobenhavn", "Storkredskode": "SK1"},
        {"Dagi_id": "OK2", "Navn": "Frederiksberg", "Storkredskode": "SK1"},
    ]
    rows = plugin.parse(data, "2025-11-18T21:00:00")
    assert len(rows) == 2
    assert rows[0]["id"] == "OK1"
    assert rows[0]["name"] == "Kobenhavn"
    assert rows[0]["storkreds_id"] == "SK1"

def test_geografi_ok_parse_skips_missing_id():
    plugin = find_plugin("Opstillingskreds-KV2025.json")
    data = [
        {"Navn": "Ingen kode", "Storkredskode": "SK1"},
        {"Dagi_id": "OK2", "Navn": "Frederiksberg", "Storkredskode": "SK1"},
    ]
    rows = plugin.parse(data, "2025-11-18T21:00:00")
    assert len(rows) == 1
    assert rows[0]["id"] == "OK2"

def test_geografi_ok_parse_non_list_returns_empty():
    plugin = find_plugin("Opstillingskreds-KV2025.json")
    assert plugin.parse({}, "2025-11-18T21:00:00") == []


# --- MATCH: Valglandsdel, Region, Kommune ---

def test_valglandsdel_matches():
    assert find_plugin("Valglandsdel-190320261917.json") is not None

def test_region_matches():
    assert find_plugin("Region-190320261917.json") is not None

def test_kommune_matches():
    assert find_plugin("Kommune-190320261917.json") is not None


# --- parse: Valglandsdel ---

def test_valglandsdel_parse_returns_rows():
    plugin = find_plugin("Valglandsdel-190320261917.json")
    data = [
        {"Bogstav": "A", "Navn": "Hovedstaden", "Type": "Landsdel"},
        {"Bogstav": "B", "Navn": "Sjælland-Syddanmark", "Type": "Landsdel"},
    ]
    rows = plugin.parse(data, "2026-03-19T19:17:00")
    assert len(rows) == 2
    assert rows[0] == {"id": "A", "name": "Hovedstaden"}
    assert rows[1] == {"id": "B", "name": "Sjælland-Syddanmark"}

def test_valglandsdel_parse_non_list_returns_empty():
    plugin = find_plugin("Valglandsdel-190320261917.json")
    assert plugin.parse({}, "2026-03-19T19:17:00") == []

def test_valglandsdel_parse_skips_missing_bogstav():
    plugin = find_plugin("Valglandsdel-190320261917.json")
    data = [{"Navn": "Hovedstaden"}, {"Bogstav": "B", "Navn": "Sjælland-Syddanmark"}]
    rows = plugin.parse(data, "2026-03-19T19:17:00")
    assert len(rows) == 1


# --- parse: Region ---

def test_region_parse_returns_rows():
    plugin = find_plugin("Region-190320261917.json")
    data = [
        {"Dagi_id": "389098", "Kode": 1081, "Navn": "Region Nordjylland"},
        {"Dagi_id": "389102", "Kode": 1083, "Navn": "Region Syddanmark"},
    ]
    rows = plugin.parse(data, "2026-03-19T19:17:00")
    assert len(rows) == 2
    assert rows[0]["id"] == "389098"
    assert rows[0]["code"] == 1081
    assert rows[0]["name"] == "Region Nordjylland"

def test_region_parse_non_list_returns_empty():
    plugin = find_plugin("Region-190320261917.json")
    assert plugin.parse({}, "2026-03-19T19:17:00") == []

def test_region_parse_skips_missing_id():
    plugin = find_plugin("Region-190320261917.json")
    data = [{"Kode": 1081, "Navn": "No ID"}, {"Dagi_id": "389102", "Kode": 1083, "Navn": "OK"}]
    rows = plugin.parse(data, "2026-03-19T19:17:00")
    assert len(rows) == 1


# --- parse: Kommune ---

def test_kommune_parse_returns_rows():
    plugin = find_plugin("Kommune-190320261917.json")
    data = [
        {"Dagi_id": "389204", "Kode": 840, "Navn": "Rebild", "Regionskode": 1081},
    ]
    rows = plugin.parse(data, "2026-03-19T19:17:00")
    assert len(rows) == 1
    assert rows[0]["id"] == "389204"
    assert rows[0]["code"] == 840
    assert rows[0]["name"] == "Rebild"
    assert rows[0]["region_id"] == "1081"

def test_kommune_parse_non_list_returns_empty():
    plugin = find_plugin("Kommune-190320261917.json")
    assert plugin.parse({}, "2026-03-19T19:17:00") == []

def test_kommune_parse_skips_missing_id():
    plugin = find_plugin("Kommune-190320261917.json")
    data = [{"Kode": 840, "Navn": "No ID"}, {"Dagi_id": "389204", "Kode": 840, "Navn": "Rebild", "Regionskode": 1081}]
    rows = plugin.parse(data, "2026-03-19T19:17:00")
    assert len(rows) == 1


# --- valgresultater edge cases ---

def test_valgresultater_parse_null_kandidater():
    plugin = find_plugin("valgresultater-Folketingsvalg-Kbh-1__-260220261823.json")
    data = {
        "AfstemningsområdeDagiId": "707732",
        "Resultatart": "ForeløbigOptælling",
        "IndenforParti": [
            {"Bogstavbetegnelse": "A", "Stemmer": 1548, "Kandidater": None},
        ],
    }
    rows = plugin.parse(data, "2026-02-26T17:23:14")
    assert len(rows) == 1
    assert rows[0]["votes"] == 1548

def test_valgresultater_parse_no_indenforparti():
    plugin = find_plugin("valgresultater-Folketingsvalg-Kbh-3__Nordvest-260220261823.json")
    data = {
        "AfstemningsområdeDagiId": "706166",
        "Resultatart": "IngenResultater",
        "AfgivneStemmer": 0,
    }
    rows = plugin.parse(data, "2026-02-26T17:23:16")
    assert rows == []
