# scripts/download_historical.py
"""
Explore SFTP structure and download historical election data for parser validation.
Usage:
  python scripts/download_historical.py                   # explore only
  python scripts/download_historical.py --download /arkiv/FV2022
"""
import argparse, logging, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from valg.fetcher import get_sftp_client, walk_remote, download_file

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)
DEST = Path(__file__).parent.parent / "data" / "historical"

def explore(sftp, path="/", depth=0):
    if depth > 3: return
    try:
        for attr in sftp.listdir_attr(path):
            full = f"{path}/{attr.filename}".replace("//", "/")
            log.info("%s%s", "  " * depth, full)
            if not attr.st_size:
                explore(sftp, full, depth + 1)
    except Exception: pass

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--download", metavar="PATH",
                   help="Remote path to download after exploring")
    args = p.parse_args()
    ssh, sftp = get_sftp_client()
    try:
        log.info("=== SFTP root ===")
        explore(sftp)
        if args.download:
            log.info("\n=== Downloading %s ===", args.download)
            for rp in walk_remote(sftp, args.download):
                if rp.endswith(".json"):
                    lp = DEST / rp.lstrip("/")
                    if not lp.exists():
                        download_file(sftp, rp, lp)
    finally:
        sftp.close(); ssh.close()

if __name__ == "__main__":
    main()
