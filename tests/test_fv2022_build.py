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


def test_build_partistemmefordeling_structure():
    from build_fv2022_scenario import build_partistemmefordeling
    result = build_partistemmefordeling(ok_id="12345", party_totals={"A": 400, "V": 350})
    assert result["Valg"]["OpstillingskredsId"] == "12345"
    parties = {p["PartiId"]: p["Stemmer"] for p in result["Valg"]["Partier"]}
    assert parties["A"] == 400
    assert parties["V"] == 350


def test_build_valgresultater_structure():
    from build_fv2022_scenario import build_valgresultater
    party_data = {
        "A": {
            "total": 100,
            "kandidater": [
                {"KandidatId": "uuid-1", "Stemmer": 40},
                {"KandidatId": "uuid-2", "Stemmer": 15},
            ],
        }
    }
    result = build_valgresultater(
        ao_id="706986",
        optaellingstype="Fintaelling",
        party_data=party_data,
    )
    vr = result["Valgresultater"]
    assert vr["AfstemningsomraadeId"] == "706986"
    assert vr["Optaellingstype"] == "Fintaelling"
    party_a = next(p for p in vr["IndenforParti"] if p["PartiId"] == "A")
    assert party_a["Partistemmer"] == 100
    assert party_a["Kandidater"] == [
        {"KandidatId": "uuid-1", "Stemmer": 40},
        {"KandidatId": "uuid-2", "Stemmer": 15},
    ]


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


def test_assign_waves_puts_small_aos_first():
    """assign_preliminary_waves assigns small AOs to early waves."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
    from build_fv2022_scenario import assign_preliminary_waves

    aos = {str(i): {"eligible_voters": i * 100, "ok_id": "ok1", "sk_id": "1"} for i in range(1, 101)}
    assignment = assign_preliminary_waves(aos, n_waves=5, island_ao_ids=set())

    # AO with fewest voters should be in wave 1 or 2
    smallest_ao = "1"
    assert assignment[smallest_ao] <= 2

    # AO with most voters should be in late wave
    largest_ao = "100"
    assert assignment[largest_ao] >= 4


def test_assign_waves_forces_islands_to_wave_01():
    """assign_preliminary_waves forces island AOs into wave 1."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
    from build_fv2022_scenario import assign_preliminary_waves

    aos = {
        "island1": {"eligible_voters": 5000, "ok_id": "ok1", "sk_id": "1"},
        "small1": {"eligible_voters": 100, "ok_id": "ok2", "sk_id": "2"},
    }
    assignment = assign_preliminary_waves(aos, n_waves=5, island_ao_ids={"island1"})
    assert assignment["island1"] == 1


def test_parse_fv2022_personal_votes_extracts_candidate_rows(tmp_path):
    """parse_fv2022_personal_votes returns {(ok_norm, ao_norm): {party_id: {name_norm: votes}}}."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
    from build_fv2022_scenario import (
        parse_fv2022_personal_votes, normalize_ok_name, normalize_ao_name, normalize_name,
    )

    csv_file = tmp_path / "results.csv"
    csv_file.write_text(
        "Opstillingskreds;Afstemningsområde;Partibogstav;Partinavn;Navn;Stemmetal\n"
        "Frederikshavnkredsen;1. Skagen;A;Socialdemokratiet;Partiliste;409\n"
        "Frederikshavnkredsen;1. Skagen;A;Socialdemokratiet;Mette Frederiksen;926\n"
        "Frederikshavnkredsen;1. Skagen;A;Socialdemokratiet;Peter Skaarup;12\n"
        "Frederikshavnkredsen;1. Skagen;V;Venstre;Partiliste;281\n"
        "Frederikshavnkredsen;1. Skagen;V;Venstre;Jakob Ellemann-Jensen;55\n",
        encoding="utf-8-sig",
    )

    result = parse_fv2022_personal_votes(csv_file)
    key = (normalize_ok_name("Frederikshavnkredsen"), normalize_ao_name("1. Skagen"))
    assert key in result
    # Partiliste rows excluded
    assert "partiliste" not in result[key].get("A", {})
    # Candidate votes present
    assert result[key]["A"][normalize_name("Mette Frederiksen")] == 926
    assert result[key]["A"][normalize_name("Peter Skaarup")] == 12
    assert result[key]["V"][normalize_name("Jakob Ellemann-Jensen")] == 55


def test_parse_fv2022_personal_votes_skips_partiliste(tmp_path):
    """parse_fv2022_personal_votes excludes Partiliste rows but includes candidate rows."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
    from build_fv2022_scenario import parse_fv2022_personal_votes, normalize_ok_name, normalize_ao_name, normalize_name

    csv_file = tmp_path / "results.csv"
    csv_file.write_text(
        "Opstillingskreds;Afstemningsområde;Partibogstav;Partinavn;Navn;Stemmetal\n"
        "Kreds1;AO1;A;SD;Partiliste;100\n"
        "Kreds1;AO1;A;SD;Anders And;42\n",
        encoding="utf-8-sig",
    )

    result = parse_fv2022_personal_votes(csv_file)
    key = (normalize_ok_name("Kreds1"), normalize_ao_name("AO1"))
    assert key in result
    party_a = result[key]["A"]
    assert "partiliste" not in party_a
    assert party_a[normalize_name("Anders And")] == 42


def test_write_fintaelling_wave_uses_real_votes(tmp_path):
    """write_fintaelling_wave writes valgresultater with real personal votes."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
    from build_fv2022_scenario import write_fintaelling_wave, normalize_ok_name, normalize_ao_name
    import json

    hierarchy = {
        "701001": {
            "ao_name": "1. Skagen",
            "ok_id": "100101",
            "ok_name": "Frederikshavnkredsen",
            "sk_id": "1",
            "sk_name": "Nordjylland",
            "eligible_voters": 500,
        }
    }
    ok_norm = normalize_ok_name("Frederikshavnkredsen")
    ao_norm = normalize_ao_name("1. Skagen")
    fv2022_votes = {(ok_norm, ao_norm): {"A": 200, "V": 150}}
    personal_votes = {
        (ok_norm, ao_norm): {
            "A": {"mette frederiksen": 80, "peter skaarup": 30},
            "V": {"jakob ellemann-jensen": 55},
        }
    }
    kandidatdata = {
        "100101": {
            "A": [
                {"id": "cand-1", "name": "Mette Frederiksen", "ballot_position": 1},
                {"id": "cand-2", "name": "Peter Skaarup", "ballot_position": 2},
            ],
            "V": [
                {"id": "cand-3", "name": "Jakob Ellemann-Jensen", "ballot_position": 1},
            ],
        }
    }

    wave_dir = tmp_path / "wave_26"
    write_fintaelling_wave(
        wave_dir=wave_dir,
        wave_index=26,
        ao_ids_in_wave=["701001"],
        hierarchy=hierarchy,
        fv2022_votes=fv2022_votes,
        kandidatdata=kandidatdata,
        personal_votes=personal_votes,
    )

    vr_files = list((wave_dir / "valgresultater").glob("*.json"))
    assert len(vr_files) == 1
    vr = json.loads(vr_files[0].read_text())["Valgresultater"]
    party_a = next(p for p in vr["IndenforParti"] if p["PartiId"] == "A")
    assert party_a["Partistemmer"] == 200
    cand_votes = {k["KandidatId"]: k["Stemmer"] for k in party_a["Kandidater"]}
    assert cand_votes["cand-1"] == 80
    assert cand_votes["cand-2"] == 30


def test_write_fintaelling_wave_zero_for_unmatched_candidate(tmp_path):
    """Candidates with no personal vote entry get Stemmer=0."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
    from build_fv2022_scenario import write_fintaelling_wave, normalize_ok_name, normalize_ao_name
    import json

    hierarchy = {
        "701001": {
            "ao_name": "Test AO",
            "ok_id": "ok1",
            "ok_name": "Test Kreds",
            "sk_id": "1",
            "sk_name": "Test SK",
            "eligible_voters": 100,
        }
    }
    ok_norm = normalize_ok_name("Test Kreds")
    ao_norm = normalize_ao_name("Test AO")
    fv2022_votes = {(ok_norm, ao_norm): {"A": 50}}
    personal_votes = {}  # No personal votes at all
    kandidatdata = {
        "ok1": {
            "A": [{"id": "cand-x", "name": "Unknown Candidate", "ballot_position": 1}]
        }
    }

    wave_dir = tmp_path / "wave_26"
    write_fintaelling_wave(
        wave_dir=wave_dir,
        wave_index=26,
        ao_ids_in_wave=["701001"],
        hierarchy=hierarchy,
        fv2022_votes=fv2022_votes,
        kandidatdata=kandidatdata,
        personal_votes=personal_votes,
    )

    vr_files = list((wave_dir / "valgresultater").glob("*.json"))
    vr = json.loads(vr_files[0].read_text())["Valgresultater"]
    party_a = next(p for p in vr["IndenforParti"] if p["PartiId"] == "A")
    assert party_a["Kandidater"][0]["Stemmer"] == 0


def test_build_fv2022_kandidatdata_from_csv_creates_json(tmp_path):
    """build_fv2022_kandidatdata_from_csv writes kandidat-data JSON from CSV candidate rows."""
    import sys, json
    sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
    from build_fv2022_scenario import build_fv2022_kandidatdata_from_csv, normalize_ok_name

    # Minimal CSV with two candidates in two parties
    csv_file = tmp_path / "results.csv"
    csv_file.write_text(
        "Opstillingskreds;Afstemningsområde;Partibogstav;Partinavn;Navn;Stemmetal\n"
        "Frederikshavnkredsen;1. Skagen;A;Socialdemokratiet;Partiliste;409\n"
        "Frederikshavnkredsen;1. Skagen;A;Socialdemokratiet;Mette Frederiksen;926\n"
        "Frederikshavnkredsen;1. Skagen;V;Venstre;Partiliste;281\n"
        "Frederikshavnkredsen;1. Skagen;V;Venstre;Jakob Ellemann-Jensen;55\n",
        encoding="utf-8-sig",
    )

    # Minimal geografi with one opstillingskreds
    geo_dir = tmp_path / "geografi"
    geo_dir.mkdir()
    ok_name_norm = normalize_ok_name("Frederikshavnkredsen")
    (geo_dir / "ok.json").write_text(json.dumps([{
        "Type": "Opstillingskreds",
        "Dagi_id": 100101,
        "Navn": "Frederikshavnkredsen",
        "Storkredskode": 10,
        "Nummer": 1,
    }]))

    output_dir = tmp_path / "kandidat-data"
    build_fv2022_kandidatdata_from_csv(csv_file, geo_dir, output_dir)

    # One JSON file written
    files = list(output_dir.glob("*.json"))
    assert len(files) == 1

    data = json.loads(files[0].read_text())
    parties = {p["Partibogstav"]: p["Kandidater"] for p in data["IndenforParti"]}

    # Both parties present
    assert "A" in parties
    assert "V" in parties

    # Candidate names preserved
    a_names = {k["Navn"] for k in parties["A"]}
    assert "Mette Frederiksen" in a_names

    # Each candidate has an Id and an Opstillingskredse entry
    for party_id, kands in parties.items():
        for k in kands:
            assert isinstance(k["Id"], int)
            assert len(k["Opstillingskredse"]) == 1
            assert k["Opstillingskredse"][0]["OpstilletIKreds"] is True
            assert k["Opstillingskredse"][0]["OpstillingskredsDagiId"] == "100101"
