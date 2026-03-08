# valg

Unofficial real-time tracker for Danish Folketing election results.

Fills the gap valg.dk misses: candidate/party drilldowns and seat-flip margins.

> See DISCLAIMER.md. This is not an official source. Always refer to valg.dk.

## Setup

    pip install -e ".[dev]"
    cp .env.example .env   # credentials are public defaults — override if needed

    # Initialise the data repo
    mkdir -p ../valg-data && cd ../valg-data && git init && cd -

## Election night

    # Option A: GitHub Actions (no server needed)
    # Fork this repo, set DATA_REPO and ELECTION_FOLDER variables — done.

    # Option B: run locally
    python -m valg sync --election-folder /Folketingsvalg-1-2024 --interval 300

    # Query results
    python -m valg status
    python -m valg flip
    python -m valg party A
    python -m valg feed

## Fintælling (next day)

    python -m valg kreds "Østerbro"
    python -m valg candidate "Mette Frederiksen"

## AI commentary (optional)

Set `VALG_AI_API_KEY` and `VALG_AI_BASE_URL` in `.env`. Any OpenAI-compatible endpoint works.

    python -m valg commentary

## Adding a new file format

Drop a file in valg/plugins/:

    TABLE = "results"
    def MATCH(filename): return "my-pattern" in filename.lower()
    def parse(data, snapshot_at): return [...]  # list of row dicts

No other changes needed.

## Data source

Election data: data.valg.dk (Netcompany / Indenrigsministeriet).
Documented at: valg/api-doc/

## License

Beerware — see LICENSE.
