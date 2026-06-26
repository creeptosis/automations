#!/usr/bin/env python3
"""
Dota 2 replay downloader (Windows).

Fetches replay URLs from the OpenDota API for a list of match IDs,
downloads the .bz2 replays, decompresses them to .dem, and saves
them into your Dota 2 replays folder so they show up in the client
under Watch -> Downloaded.

USAGE
-----
1. Install the one dependency (open Command Prompt or PowerShell):
       pip install requests

2. Feed in match IDs either way:
   - Paste them into the MATCH_IDS list below, OR
   - Put one match ID per line in a file and pass it:
         python download_replays.py match_ids.txt
     (a .csv works too; the script grabs the first number on each line)

3. Run:
       python download_replays.py
   or
       python download_replays.py match_ids.txt

NOTES
-----
- Valve only keeps replays for a limited time. If a replay has expired,
  OpenDota returns no replay_url and the script will tell you — nothing
  can recover an expired replay.
- If a match isn't parsed yet, the script asks OpenDota to parse it,
  then skips it for now. Wait ~1 minute and re-run to grab those.
"""

import bz2
import os
import re
import sys
import time

import requests

# ---------------------------------------------------------------------------
# CONFIG — edit these two if needed
# ---------------------------------------------------------------------------

# Your Dota 2 replays folder. Default Steam install path on Windows.
# If your Steam library is on another drive, change this (keep the r"" prefix).
REPLAY_DIR = r"C:\Program Files (x86)\Steam\steamapps\common\dota 2 beta\game\dota\replays"

# Option A: paste match IDs here (used when you DON'T pass a file argument).
MATCH_IDS = [
    8863091025,
    # 8123456790,
]

# ---------------------------------------------------------------------------

OPENDOTA = "https://api.opendota.com/api"


def load_ids_from_file(path):
    """Read match IDs from a text/CSV file: first integer found on each line."""
    ids = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            m = re.search(r"\d{6,}", line)  # match IDs are long integers
            if m:
                ids.append(int(m.group()))
    return ids


def get_match(match_id):
    """Fetch match JSON from OpenDota. Returns dict or None on hard failure."""
    try:
        r = requests.get(f"{OPENDOTA}/matches/{match_id}", timeout=20)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        print(f"  [error] could not reach OpenDota for {match_id}: {e}")
        return None


def request_parse(match_id):
    """Ask OpenDota to parse a match so a replay_url becomes available."""
    try:
        requests.post(f"{OPENDOTA}/request/{match_id}", timeout=20)
    except requests.RequestException:
        pass  # best effort; non-fatal


def build_replay_url(match):
    """Return a usable replay_url from the match JSON, or None."""
    if match.get("replay_url"):
        return match["replay_url"]
    # Some responses give the pieces instead of a full URL.
    cluster = match.get("cluster")
    salt = match.get("replay_salt")
    mid = match.get("match_id")
    if cluster and salt and mid:
        return f"http://replay{cluster}.valve.net/570/{mid}_{salt}.dem.bz2"
    return None


def download_and_extract(match_id, url, dest_dir):
    """Download .bz2 replay and decompress to .dem in dest_dir."""
    dem_path = os.path.join(dest_dir, f"{match_id}.dem")
    if os.path.exists(dem_path):
        print(f"  already have {match_id}.dem — skipping")
        return True
    try:
        print(f"  downloading {url}")
        resp = requests.get(url, timeout=120, stream=True)
        resp.raise_for_status()
        compressed = resp.content
        print(f"  decompressing ({len(compressed) // 1024} KB)...")
        data = bz2.decompress(compressed)
        with open(dem_path, "wb") as f:
            f.write(data)
        print(f"  saved -> {dem_path}")
        return True
    except requests.RequestException as e:
        print(f"  [error] download failed for {match_id}: {e}")
    except OSError as e:
        print(f"  [error] could not write file for {match_id}: {e}")
    return False


def main():
    # Decide where IDs come from
    if len(sys.argv) > 1:
        ids = load_ids_from_file(sys.argv[1])
        print(f"Loaded {len(ids)} match IDs from {sys.argv[1]}")
    else:
        ids = list(MATCH_IDS)
        print(f"Using {len(ids)} match IDs from the script's MATCH_IDS list")

    if not ids:
        print("No match IDs to process. Pass a file, or fill in MATCH_IDS.")
        return

    os.makedirs(REPLAY_DIR, exist_ok=True)
    print(f"Saving replays to: {REPLAY_DIR}\n")

    need_parse = []
    ok = 0

    for match_id in ids:
        print(f"Match {match_id}")
        match = get_match(match_id)
        if not match:
            continue

        url = build_replay_url(match)
        if not url:
            print("  no replay_url yet — requesting a parse from OpenDota")
            request_parse(match_id)
            need_parse.append(match_id)
            time.sleep(1)  # be polite to the free API
            continue

        if download_and_extract(match_id, url, REPLAY_DIR):
            ok += 1
        time.sleep(1)

    print("\n--- done ---")
    print(f"Downloaded/verified: {ok}")
    if need_parse:
        print(f"Needed parsing (re-run in ~1 min to get these): {need_parse}")
    print("\nIn Dota: Watch -> Downloaded should now list these matches.")


if __name__ == "__main__":
    main()