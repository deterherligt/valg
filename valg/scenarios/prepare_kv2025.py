"""
One-time preparation script: download KV2025 data from SFTP and generate
pre-sorted wave bundles in valg/scenarios/kv2025/.

Run from the valg/ repo root:
    python -m valg.scenarios.prepare_kv2025

Requires VALG_SFTP_* env vars (same credentials as production sync).
Output: valg/scenarios/kv2025/wave_00/ through wave_NN/ with FV-format JSON files.

Re-running is safe — output directory is cleared first.
"""
from __future__ import annotations

import io
import json
import logging
import shutil
from pathlib import Path

from valg.fetcher import get_sftp_client
from valg.scenarios.kv2025_transform import (
    FT_PARTY_LETTERS,
    aggregate_partistemmer,
    build_party_registry,
    bucket_aos,
    transform_geography_files,
    transform_kandidatdata_json,
    transform_storkreds_json,
    transform_valgresultater_final,
    transform_valgresultater_preliminary,
    assign_candidates_to_ok,
)

log = logging.getLogger(__name__)

SFTP_FOLDER = "data/kommunalvalg-134-18-11-2025"
OUTPUT_DIR = Path(__file__).parent / "kv2025"
ELECTION_ID = "KV2025"

# Voter-count thresholds for preliminary wave buckets (11 buckets)
PRELIMINARY_THRESHOLDS = [500, 1000, 1500, 2000, 2500, 3000, 3500, 4000, 5000, 7000]

# base_interval_s per preliminary bucket (index 0..10)
PRELIMINARY_INTERVALS = [90, 75, 60, 55, 50, 45, 40, 40, 45, 55, 70, 90]

# Fintælling groups: each is a list of preliminary bucket indices to merge
FINAL_GROUPS = [[0, 1], [2, 3], [4, 5], [6, 7], [8, 9], [10]]
FINAL_INTERVALS = [75, 60, 55, 55, 65, 90]


def _read_json(sftp, path: str) -> dict | list:
    buf = io.BytesIO()
    sftp.getfo(path, buf)
    return json.loads(buf.getvalue())


def _list_json(sftp, folder: str) -> list[str]:
    return [
        f"{folder}/{f}"
        for f in sftp.listdir(folder)
        if f.endswith(".json") and not f.endswith(".hash")
    ]


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2))


def _write_meta(wave_dir: Path, label: str, interval_s: float, phase: str) -> None:
    _write(wave_dir / "_meta.json", {
        "label": label,
        "interval_s": interval_s,
        "phase": phase,
    })


def run(sftp) -> None:
    base = SFTP_FOLDER

    # ── 1. Download raw data ───────────────────────────────────────────────

    log.info("Downloading geografi...")
    geo_files = sftp.listdir(f"{base}/geografi")
    kommune_file = next(f for f in geo_files if f.startswith("Kommune-") and not f.endswith(".hash"))
    ok_file = next(f for f in geo_files if f.startswith("Opstillingskreds-") and not f.endswith(".hash"))
    ao_file = next(f for f in geo_files if f.startswith("Afstemningsomraade-") and not f.endswith(".hash"))

    kommuner: list[dict] = _read_json(sftp, f"{base}/geografi/{kommune_file}")

    # SFTP opstillingskredse use Dagi_id as key, Kredskommunekode for parent kommune.
    # Normalise to Kode / KommuneKode as expected by transform functions.
    _raw_oks: list[dict] = _read_json(sftp, f"{base}/geografi/{ok_file}")
    opstillingskredse: list[dict] = [
        {**ok, "Kode": ok["Dagi_id"], "KommuneKode": ok["Kredskommunekode"]}
        for ok in _raw_oks
    ]

    # SFTP AO records use Opstillingskreds_Dagi_id for OK reference.
    # Voter count is not present in geografi; we back-fill from valgresultater later.
    _raw_aos: list[dict] = _read_json(sftp, f"{base}/geografi/{ao_file}")
    # Build initial AO list with normalised field names
    afstemningsomraader: list[dict] = [
        {
            **ao,
            "OpstillingskredsKode": ao["Opstillingskreds_Dagi_id"],
            "StemmeberettigeteVaelgere": 0,  # placeholder; filled below after valgresultater load
        }
        for ao in _raw_aos
    ]

    log.info("  %d kommuner, %d opstillingskredse, %d afstemningsomraader",
             len(kommuner), len(opstillingskredse), len(afstemningsomraader))

    log.info("Downloading mandatfordeling...")
    mf_files = [f for f in sftp.listdir(f"{base}/mandatfordeling")
                if f.endswith(".json") and not f.endswith(".hash")]
    mandatfordeling: dict[int, int] = {}
    for fname in mf_files:
        data = _read_json(sftp, f"{base}/mandatfordeling/{fname}")
        if isinstance(data, dict) and "Kommunekode" in data:
            # AntalMandater is not present; derive from length of PersonligeMandater
            mandatfordeling[data["Kommunekode"]] = len(data.get("PersonligeMandater", []))
    log.info("  %d kommuner with mandatfordeling", len(mandatfordeling))

    log.info("Downloading kandidat-data...")
    kd_files = [f for f in sftp.listdir(f"{base}/kandidat-data")
                if f.endswith(".json") and not f.endswith(".hash")]
    kd_by_kommune: dict[str, dict] = {}
    for fname in kd_files:
        data = _read_json(sftp, f"{base}/kandidat-data/{fname}")
        if isinstance(data, dict):
            kd_by_kommune[data.get("Kommune", fname)] = data
    log.info("  %d kommuner with kandidat-data", len(kd_by_kommune))

    log.info("Downloading valgresultater...")
    vr_files = [f for f in sftp.listdir(f"{base}/valgresultater")
                if f.endswith(".json") and not f.endswith(".hash")]
    # Each file is one AO's results — keyed by AfstemningsomraadeDagiId (ascii normalised)
    # SFTP uses ø-spelling: AfstemningsområdeDagiId; we normalise to ascii for transform compat
    ao_results: dict[str, dict] = {}
    for fname in vr_files:
        data = _read_json(sftp, f"{base}/valgresultater/{fname}")
        if not isinstance(data, dict):
            continue
        raw_id = data.get("AfstemningsområdeDagiId") or data.get("AfstemningsomraadeDagiId")
        if raw_id is None:
            continue
        ao_id = str(raw_id)
        # Normalise key to ascii spelling expected by transform functions
        data["AfstemningsomraadeDagiId"] = ao_id
        ao_results[ao_id] = data
    log.info("  %d AO results downloaded", len(ao_results))

    log.info("Downloading valgdeltagelse...")
    vd_files = [f for f in sftp.listdir(f"{base}/valgdeltagelse")
                if f.endswith(".json") and not f.endswith(".hash")]
    ao_turnout: dict[str, dict] = {}
    for fname in vd_files:
        data = _read_json(sftp, f"{base}/valgdeltagelse/{fname}")
        if isinstance(data, dict):
            # SFTP uses ø-spelling
            raw_id = data.get("AfstemningsområdeDagiId") or data.get("AfstemningsomraadeDagiId")
            if raw_id is not None:
                ao_id = str(raw_id)
                ao_turnout[ao_id] = data
    log.info("  %d AO turnout files downloaded", len(ao_turnout))

    # Back-fill voter counts from valgresultater into afstemningsomraader
    # (geografi files don't carry StemmeberettigeteVaelgere for KV2025)
    for ao in afstemningsomraader:
        result = ao_results.get(ao["Dagi_id"])
        if result:
            ao["StemmeberettigeteVaelgere"] = result.get("AntalStemmeberettigedeVælgere", 0)

    # ── 2. Build lookup tables ─────────────────────────────────────────────

    # AO Dagi_id → opstillingskreds Kode (str)
    ao_to_ok: dict[str, str] = {
        ao["Dagi_id"]: str(ao["OpstillingskredsKode"])
        for ao in afstemningsomraader
    }

    # OK Kode (str) → storkreds (kommune) Kode (str)
    ok_to_storkreds: dict[str, str] = {
        str(ok["Kode"]): str(ok["KommuneKode"])
        for ok in opstillingskredse
    }

    # OK Kode (str) → total eligible voters in that OK
    ok_voters: dict[str, int] = {}
    for ao in afstemningsomraader:
        ok_id = str(ao["OpstillingskredsKode"])
        ok_voters[ok_id] = ok_voters.get(ok_id, 0) + ao.get("StemmeberettigeteVaelgere", 0)

    # ── 3. Build party registry ────────────────────────────────────────────

    all_result_lists = [
        r.get("Kandidatlister", [])
        for r in ao_results.values()
    ]
    party_registry = build_party_registry(all_result_lists)
    log.info("Party registry: %s", sorted(party_registry.keys()))

    # ── 4. Build candidate list ────────────────────────────────────────────

    all_candidates: list[dict] = []
    for kommune_name, kd in kd_by_kommune.items():
        kommune_kode = next(
            (k["Kode"] for k in kommuner if k["Navn"] == kommune_name), None
        )
        if kommune_kode is None:
            log.warning("  No kommune match for kandidat-data key %r", kommune_name)
            continue
        for valgforbund_or_list in kd.get("Kandidatlister", []):
            letter = valgforbund_or_list.get("Bogstavbetegnelse", "")
            if letter not in FT_PARTY_LETTERS:
                continue
            kandidater = valgforbund_or_list.get("Kandidater", [])
            assigned = assign_candidates_to_ok(
                kandidater, letter, kommune_kode, ok_voters, ok_to_storkreds
            )
            all_candidates.extend(assigned)
    log.info("  %d candidates assigned", len(all_candidates))

    # ── 5. Sort and bucket AOs ─────────────────────────────────────────────

    aos_with_voters = [
        {"id": ao["Dagi_id"], "eligible_voters": ao.get("StemmeberettigeteVaelgere", 0)}
        for ao in afstemningsomraader
        if ao["Dagi_id"] in ao_results  # only AOs with result data
    ]
    prelim_buckets = bucket_aos(aos_with_voters, PRELIMINARY_THRESHOLDS)
    log.info("Preliminary buckets: %s", [len(b) for b in prelim_buckets])

    # Fintælling buckets: merge preliminary buckets per FINAL_GROUPS
    final_buckets = []
    for group in FINAL_GROUPS:
        merged = []
        for idx in group:
            if idx < len(prelim_buckets):
                merged.extend(prelim_buckets[idx])
        if merged:
            final_buckets.append(merged)

    # ── 6. Clear output dir ────────────────────────────────────────────────

    if OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)
    OUTPUT_DIR.mkdir(parents=True)

    # ── 7. Wave 00: setup (Storkreds.json + geografi + kandidat-data) ──────

    wave00 = OUTPUT_DIR / "wave_00"
    _write_meta(wave00, "Setup — geografi & kandidater", 0.0, "setup")

    storkreds_data = transform_storkreds_json(kommuner, mandatfordeling)
    _write(wave00 / "Storkreds.json", storkreds_data)

    geo = transform_geography_files(opstillingskredse, afstemningsomraader)
    _write(wave00 / "geografi" / "Opstillingskreds-KV2025.json", geo["Opstillingskreds"])
    _write(wave00 / "geografi" / "Afstemningsomraade-KV2025.json", geo["Afstemningsomraade"])

    kd_json = transform_kandidatdata_json(party_registry, all_candidates)
    _write(wave00 / "kandidat-data" / "kandidat-data-Folketingsvalg-KV2025.json", kd_json)

    log.info("Wrote wave_00 (setup)")

    # ── 8. Preliminary waves ───────────────────────────────────────────────

    # Track all AO results seen so far for running partistemmer totals
    seen_ao_results: list[dict] = []

    for bucket_idx, bucket in enumerate(prelim_buckets):
        wave_num = bucket_idx + 1
        wave_dir = OUTPUT_DIR / f"wave_{wave_num:02d}"
        interval = PRELIMINARY_INTERVALS[min(bucket_idx, len(PRELIMINARY_INTERVALS) - 1)]
        label = f"Foreløbig — batch {wave_num} ({len(bucket)} stemmeafgivelsesområder)"
        _write_meta(wave_dir, label, float(interval), "preliminary")

        batch_ao_results = []
        for ao in bucket:
            ao_id = ao["id"]
            if ao_id not in ao_results:
                continue
            result = ao_results[ao_id]
            prelim = transform_valgresultater_preliminary(result, party_registry)
            _write(wave_dir / "valgresultater" / f"valgresultater-Folketingsvalg-{ao_id}.json", prelim)

            if ao_id in ao_turnout:
                _write(wave_dir / "valgdeltagelse" / f"valgdeltagelse-{ao_id}.json", ao_turnout[ao_id])

            batch_ao_results.append(result)

        seen_ao_results.extend(batch_ao_results)

        # Write running partistemmer totals for all AOs seen so far
        partistemmer = aggregate_partistemmer(seen_ao_results, party_registry, ao_to_ok)
        for ok_id, data in partistemmer.items():
            _write(wave_dir / "partistemmefordeling" / f"partistemmefordeling-{ok_id}.json", data)

        log.info("Wrote wave_%02d: %d AOs, %d OK partistemmer", wave_num, len(bucket), len(partistemmer))

    # ── 9. Fintælling waves ────────────────────────────────────────────────

    prelim_wave_count = len(prelim_buckets)
    for grp_idx, group_bucket in enumerate(final_buckets):
        wave_num = prelim_wave_count + 1 + grp_idx
        wave_dir = OUTPUT_DIR / f"wave_{wave_num:02d}"
        interval = FINAL_INTERVALS[min(grp_idx, len(FINAL_INTERVALS) - 1)]
        label = f"Fintælling — batch {grp_idx + 1} ({len(group_bucket)} stemmeafgivelsesområder)"
        _write_meta(wave_dir, label, float(interval), "final")

        for ao in group_bucket:
            ao_id = ao["id"]
            if ao_id not in ao_results:
                continue
            result = ao_results[ao_id]
            final = transform_valgresultater_final(result, party_registry)
            _write(wave_dir / "valgresultater" / f"valgresultater-Folketingsvalg-{ao_id}.json", final)

        log.info("Wrote wave_%02d (fintælling batch %d): %d AOs", wave_num, grp_idx + 1, len(group_bucket))

    log.info("Done. Wrote %d waves to %s", prelim_wave_count + len(final_buckets) + 1, OUTPUT_DIR)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    log.info("Connecting to SFTP...")
    ssh, sftp = get_sftp_client()
    try:
        run(sftp)
    finally:
        sftp.close()
        ssh.close()


if __name__ == "__main__":
    main()
