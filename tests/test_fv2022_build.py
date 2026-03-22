"""Unit tests for fv2022 build script helpers."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))


def test_normalize_name_lowercases():
    from build_fv2022_scenario import normalize_name
    assert normalize_name("Frederikshavnkredsen") == "frederikshavnkredsen"


def test_normalize_name_strips_accents():
    from build_fv2022_scenario import normalize_name
    # Danish romanisation: ø->oe, æ->ae, å->aa
    assert normalize_name("Afstemningsområde") == "afstemningsomraade"
    assert normalize_name("Ærø") == "aeroe"
    assert normalize_name("Ålborg") == "aalborg"
    assert normalize_name("Læsø") == "laesoe"


def test_normalize_name_collapses_whitespace():
    from build_fv2022_scenario import normalize_name
    assert normalize_name("1.  Skagen  ") == "1. skagen"


def test_normalize_name_strips_leading_numbers_dot():
    from build_fv2022_scenario import normalize_name
    assert normalize_name("1. Skagen") == "1. skagen"


def test_distribute_votes_sums_to_party_total():
    from build_fv2022_scenario import distribute_candidate_votes
    candidates = [{"id": f"c{i}", "ballot_position": i} for i in range(1, 6)]
    result = distribute_candidate_votes(100, candidates)
    assert sum(result) == 100


def test_distribute_votes_position_one_gets_most():
    from build_fv2022_scenario import distribute_candidate_votes
    candidates = [{"id": f"c{i}", "ballot_position": i} for i in range(1, 6)]
    result = distribute_candidate_votes(100, candidates)
    assert result[0] >= result[1]
    assert result[1] >= result[2]


def test_distribute_votes_position_one_gets_35_percent():
    from build_fv2022_scenario import distribute_candidate_votes
    candidates = [{"id": f"c{i}", "ballot_position": i} for i in range(1, 6)]
    result = distribute_candidate_votes(200, candidates)
    # Position 1 gets 35% = 70, remainder assigned there
    assert result[0] >= 70


def test_distribute_votes_zero_party_total():
    from build_fv2022_scenario import distribute_candidate_votes
    candidates = [{"id": f"c{i}", "ballot_position": i} for i in range(1, 4)]
    result = distribute_candidate_votes(0, candidates)
    assert result == [0, 0, 0]


def test_distribute_votes_empty_candidates():
    from build_fv2022_scenario import distribute_candidate_votes
    assert distribute_candidate_votes(100, []) == []


def test_build_partistemmefordeling_structure():
    from build_fv2022_scenario import build_partistemmefordeling
    result = build_partistemmefordeling(ok_id="12345", party_totals={"A": 400, "V": 350})
    assert result["Valg"]["OpstillingskredsId"] == "12345"
    parties = {p["PartiId"]: p["Stemmer"] for p in result["Valg"]["Partier"]}
    assert parties["A"] == 400
    assert parties["V"] == 350


def test_build_valgresultater_structure():
    from build_fv2022_scenario import build_valgresultater
    candidates = [{"id": "uuid-1", "ballot_position": 1}, {"id": "uuid-2", "ballot_position": 2}]
    result = build_valgresultater(
        ao_id="706986",
        optaellingstype="Fintaelling",
        party_data={"A": {"total": 100, "candidates_by_ok": {"ok-1": candidates}}},
        ao_ok_id="ok-1",
    )
    vr = result["Valgresultater"]
    assert vr["AfstemningsomraadeId"] == "706986"
    assert vr["Optaellingstype"] == "Fintaelling"
    party_a = next(p for p in vr["IndenforParti"] if p["PartiId"] == "A")
    assert party_a["Partistemmer"] == 100
    assert len(party_a["Kandidater"]) == 2
    assert sum(k["Stemmer"] for k in party_a["Kandidater"]) == 100


def test_parse_fv2022_csv_extracts_party_votes(tmp_path):
    """parse_fv2022_csv extracts Partiliste rows only, keyed by (ok_norm, ao_norm)."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
    from build_fv2022_scenario import parse_fv2022_csv, normalize_ok_name, normalize_ao_name

    csv_file = tmp_path / "results.csv"
    csv_file.write_text(
        "Opstillingskreds;Afstemningsområde;Partibogstav;Partinavn;Navn;Stemmetal\n"
        "Frederikshavnkredsen;1. Skagen;A;Socialdemokratiet;Partiliste;409\n"
        "Frederikshavnkredsen;1. Skagen;A;Socialdemokratiet;Mette Frederiksen;926\n"
        "Frederikshavnkredsen;1. Skagen;V;Venstre;Partiliste;281\n",
        encoding="utf-8-sig"
    )

    result = parse_fv2022_csv(csv_file)
    key = (normalize_ok_name("Frederikshavnkredsen"), normalize_ao_name("1. Skagen"))
    assert key in result
    assert result[key]["A"] == 409   # Only Partiliste row
    assert result[key]["V"] == 281


def test_build_id_mapping_joins_by_name(tmp_path):
    """build_id_mapping returns {(ok_norm, ao_norm): ao_id} from geografi hierarchy."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
    from build_fv2022_scenario import build_id_mapping, normalize_ok_name, normalize_ao_name

    hierarchy = {
        "100101": {"ao_name": "1. Skagen", "ok_id": "1001", "ok_name": "Frederikshavnkredsen",
                   "sk_id": "1", "eligible_voters": 500},
    }
    mapping = build_id_mapping(hierarchy)
    key = (normalize_ok_name("Frederikshavnkredsen"), normalize_ao_name("1. Skagen"))
    assert mapping[key] == "100101"
