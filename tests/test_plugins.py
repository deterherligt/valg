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

def test_geografi_matches_region():
    assert find_plugin("Region.json") is not None

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
    plugin = find_plugin("Region.json")
    data = json.loads((FIXTURES / "geografi_region.json").read_text())
    rows = plugin.parse(data, "2024-11-05T21:00:00")
    assert len(rows) == 2
    assert all("id" in r and "name" in r for r in rows)

def test_geografi_parse_includes_n_kredsmandater():
    plugin = find_plugin("Region.json")
    data = json.loads((FIXTURES / "geografi_region.json").read_text())
    rows = plugin.parse(data, "2024-11-05T21:00:00")
    assert all("n_kredsmandater" in r for r in rows)
    assert rows[0]["n_kredsmandater"] == 15

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
    plugin = find_plugin("Region.json")
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
