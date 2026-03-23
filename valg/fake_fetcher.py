"""
Fake fetcher for firedrill testing.

Generates valg.dk-format JSON files from synthetic election data, wave by wave.
Bypasses SFTP entirely — writes directly to a local data directory.

Wave schedule:
  0 — setup: Storkreds-{ts}.json + kandidat-data (geography/candidates)
  1 — 25% districts preliminary
  2 — 50% districts preliminary
  3 — 100% districts preliminary
  4 — 50% districts fintaelling
  5 — 100% districts fintaelling
"""
import json
import random
from datetime import datetime
from pathlib import Path

ELECTION_ID = "FV2024"
SEED = 42
WAVE_FRACTIONS = {1: 0.25, 2: 0.50, 3: 1.0, 4: 0.50, 5: 1.0}


def make_election(
    n_parties: int = 6,
    n_storkredse: int = 3,
    n_districts: int = 30,
    seed: int = SEED,
) -> dict:
    """Generate a small but realistic synthetic election structure."""
    from tests.synthetic.generator import generate_election
    return generate_election(
        n_parties=n_parties,
        n_storkredse=n_storkredse,
        n_districts=n_districts,
        seed=seed,
    )


def setup_db(conn, election: dict) -> None:
    """
    Seed geography, parties, and candidates directly into the DB.
    """
    election_id = ELECTION_ID
    conn.execute(
        "INSERT OR REPLACE INTO elections (id, name) VALUES (?, ?)",
        (election_id, "Syntetisk Valg 2024"),
    )
    for sk in election["storkredse"]:
        conn.execute(
            "INSERT OR REPLACE INTO storkredse (id, name, election_id, n_kredsmandater) VALUES (?,?,?,?)",
            (sk["id"], sk["name"], election_id, sk["n_kredsmandater"]),
        )
    for ok in election["opstillingskredse"]:
        conn.execute(
            "INSERT OR REPLACE INTO opstillingskredse (id, name, storkreds_id) VALUES (?,?,?)",
            (ok["id"], ok["name"], ok["storkreds_id"]),
        )
    for ao in election["afstemningsomraader"]:
        conn.execute(
            "INSERT OR REPLACE INTO afstemningsomraader (id, name, opstillingskreds_id, municipality_name, eligible_voters) VALUES (?,?,?,?,?)",
            (ao["id"], ao["name"], ao["opstillingskreds_id"], ao["municipality_name"], ao["eligible_voters"]),
        )
    for p in election["parties"]:
        conn.execute(
            "INSERT OR REPLACE INTO parties (id, letter, name, election_id) VALUES (?,?,?,?)",
            (p["id"], p["letter"], p["name"], election_id),
        )
    for c in election["candidates"]:
        conn.execute(
            "INSERT OR REPLACE INTO candidates (id, name, party_id, opstillingskreds_id, ballot_position) VALUES (?,?,?,?,?)",
            (c["id"], c["name"], c["party_id"], c["opstillingskreds_id"], c["ballot_position"]),
        )
    conn.commit()


def _timestamp() -> str:
    return datetime.now().strftime("%d%m%Y%H%M")


def write_wave(data_dir: Path, election: dict, wave: int) -> list[Path]:
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(SEED + wave)

    written = []
    if wave == 0:
        written += _write_storkreds(data_dir, election)
        written += _write_kandidatdata(data_dir, election)
    elif wave in (1, 2, 3):
        fraction = WAVE_FRACTIONS[wave]
        districts = _select_districts(election["afstemningsomraader"], fraction, rng)
        written += _write_partistemmer(data_dir, election, districts, rng)
        written += _write_valgresultater_preliminary(data_dir, election, districts, rng)
        written += _write_valgdeltagelse(data_dir, election, districts, rng)
    elif wave in (4, 5):
        fraction = WAVE_FRACTIONS[wave]
        districts = _select_districts(election["afstemningsomraader"], fraction, rng)
        written += _write_valgresultater_final(data_dir, election, districts, rng)
    return written


def _select_districts(all_districts: list, fraction: float, rng: random.Random) -> list:
    n = max(1, int(len(all_districts) * fraction))
    return sorted(all_districts, key=lambda d: d["id"])[:n]


def _write(path: Path, data) -> Path:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    return path


def _write_storkreds(data_dir: Path, election: dict) -> list[Path]:
    data = [
        {"Nummer": sk["id"], "Navn": sk["name"], "Type": "Storkreds",
         "OprettetUtc": None, "OpdateretUtc": None, "Valglandsdelkode": None}
        for sk in election["storkredse"]
    ]
    return [_write(data_dir / f"Storkreds-{_timestamp()}.json", data)]


def _write_kandidatdata(data_dir: Path, election: dict) -> list[Path]:
    by_party: dict[str, list] = {}
    for c in election["candidates"]:
        by_party.setdefault(c["party_id"], []).append(c)
    party_map = {p["id"]: p for p in election["parties"]}

    data = {
        "Valgart": "Folketingsvalg",
        "Valgdag": "01-01-2024",
        "FrigivelsesTidspunktUTC": None,
        "OpdateringsTidspunktUTC": None,
        "Storkreds": "Test",
        "Storkredsnummer": "1",
        "IndenforParti": [
            {
                "PartiId": party_id,
                "Bogstavbetegnelse": party_map.get(party_id, {}).get("letter", party_id),
                "Partinavn": party_map.get(party_id, {}).get("name", ""),
                "Stemmeseddelsplacering": 0,
                "PersonligeStemmer": True,
                "Kandidater": [
                    {
                        "Id": c["id"],
                        "Navn": c["name"],
                        "Stemmeseddelnavn": c["name"],
                        "Stilling": "",
                        "AlfabetiskSorteretPlacering": idx + 1,
                        "Opstillingskredse": [
                            {
                                "Opstillingsform": "Sideordnet",
                                "Opstillingskreds": c.get("opstillingskreds_id", ""),
                                "OpstillingskredsDagiId": c.get("opstillingskreds_id", ""),
                                "OpstilletIKreds": True,
                                "KandidatsPlacering": c.get("ballot_position", 1),
                            }
                        ],
                    }
                    for idx, c in enumerate(candidates)
                ],
            }
            for party_id, candidates in by_party.items()
        ],
        "UdenforParti": {"Kandidater": []},
    }
    return [_write(data_dir / f"kandidat-data-Folketingsvalg-{ELECTION_ID}-{_timestamp()}.json", data)]


def _write_partistemmer(data_dir: Path, election: dict, districts: list, rng: random.Random) -> list[Path]:
    ok_districts: dict[str, list] = {}
    for ao in districts:
        ok_districts.setdefault(ao["opstillingskreds_id"], []).append(ao)
    party_map = {p["id"]: p for p in election["parties"]}

    written = []
    for ok_id, aos in ok_districts.items():
        data = {
            "Valgart": "Folketingsvalg",
            "Valgdag": "01-01-2024",
            "FrigivelsesTidspunktUTC": None,
            "Storkreds": "",
            "Storkredsnummer": "",
            "Opstillingskreds": ok_id,
            "OpstillingskredsDagiId": ok_id,
            "IndenforParti": [
                {
                    "Bogstavbetegnelse": party_map.get(p["id"], {}).get("letter", p["id"]),
                    "PartiNavn": p["name"],
                    "Stemmer": rng.randint(100, 5000),
                    "Kandidater": [],
                }
                for p in election["parties"]
            ],
        }
        written.append(_write(data_dir / f"partistemmefordeling-{ok_id}-{_timestamp()}.json", data))
    return written


def _write_valgresultater_preliminary(data_dir: Path, election: dict, districts: list, rng: random.Random) -> list[Path]:
    party_map = {p["id"]: p for p in election["parties"]}
    written = []
    for ao in districts:
        data = {
            "Valgart": "Folketingsvalg",
            "Valgdag": "01-01-2024",
            "FrigivelsesTidspunktUTC": None,
            "AfstemningsområdeDagiId": ao["id"],
            "Afstemningsområde": ao["name"],
            "Resultatart": "Foreløbig",
            "IndenforParti": [
                {
                    "Bogstavbetegnelse": party_map.get(p["id"], {}).get("letter", p["id"]),
                    "Stemmer": rng.randint(50, 1000),
                    "Kandidater": [],
                }
                for p in election["parties"]
            ],
        }
        written.append(_write(data_dir / f"valgresultater-Folketingsvalg-{ao['id']}-{_timestamp()}.json", data))
    return written


def _write_valgresultater_final(data_dir: Path, election: dict, districts: list, rng: random.Random) -> list[Path]:
    ok_party_cands: dict[tuple, list] = {}
    for c in election["candidates"]:
        ok_party_cands.setdefault((c["opstillingskreds_id"], c["party_id"]), []).append(c)
    party_map = {p["id"]: p for p in election["parties"]}

    written = []
    for ao in districts:
        ok_id = ao["opstillingskreds_id"]
        data = {
            "Valgart": "Folketingsvalg",
            "Valgdag": "01-01-2024",
            "FrigivelsesTidspunktUTC": None,
            "AfstemningsområdeDagiId": ao["id"],
            "Afstemningsområde": ao["name"],
            "Resultatart": "Endelig",
            "IndenforParti": [
                {
                    "Bogstavbetegnelse": party_map.get(p["id"], {}).get("letter", p["id"]),
                    "Stemmer": rng.randint(50, 1000),
                    "Kandidater": [
                        {"Id": c["id"], "Stemmeseddelnavn": c["name"], "Stemmer": rng.randint(5, 300)}
                        for c in ok_party_cands.get((ok_id, p["id"]), [])
                    ],
                }
                for p in election["parties"]
            ],
        }
        written.append(_write(data_dir / f"valgresultater-Folketingsvalg-{ao['id']}-{_timestamp()}.json", data))
    return written


def _write_valgdeltagelse(data_dir: Path, election: dict, districts: list, rng: random.Random) -> list[Path]:
    written = []
    for ao in districts:
        eligible = ao.get("eligible_voters", 3000)
        cast = rng.randint(int(eligible * 0.6), eligible)
        data = {
            "Valgart": "Folketingsvalg",
            "Valgdag": "01-01-2024",
            "FrigivelsesTidspunktUTC": None,
            "AfstemningsområdeDagiId": ao["id"],
            "Afstemningsområde": ao["name"],
            "Valgdeltagelse": [
                {
                    "AntalStemmeberretigedeVælgere": eligible,
                    "AfgivneStemmer": cast,
                }
            ],
        }
        written.append(_write(data_dir / f"valgdeltagelse-{ao['id']}-{_timestamp()}.json", data))
    return written
