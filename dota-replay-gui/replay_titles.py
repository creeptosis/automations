#!/usr/bin/env python3
"""
Read AND write Dota 2's custom replay names (the "Rename" title in Watch -> Downloaded).

Dota does NOT rename the .dem file when you rename a replay. Files stay {match_id}.dem;
the custom name is stored as a `title` field, keyed by match_id, inside Steam's per-user:

    <Steam>\\userdata\\<id>\\570\\remote\\cfg\\downloaded_replays_info.dat

FILE FORMAT (fully reverse-engineered, round-trip byte-exact):
    bytes 0..3   magic  "VBKV"
    bytes 4..7   CRC32 of the body (everything after byte 8), little-endian
    bytes 8..    Valve Binary KeyValues tree:
        DownloadsInfo
        └── download0..N
            ├── match { match_id(uint64), start_time, duration, game_mode, players{...} }
            ├── title   <-- the custom name (string); present only once you've set one
            ├── size
            └── exists_on_disk
    VBKV value-type bytes: 0x00 nested, 0x01 string, 0x02 int32, 0x03 float,
                           0x07 uint64, 0x0B end-of-block.

Writing is SAFE here: we (1) refuse if Dota 2 is running (it would overwrite on exit),
(2) verify the current file round-trips byte-exact before trusting our serializer,
(3) keep a .bak, (4) write atomically, (5) recompute the CRC32, (6) re-read to verify.

CLI:
    python replay_titles.py dump                 # match_id -> title (JSON)
    python replay_titles.py watch [secs]         # report .dat changes live
    python replay_titles.py selftest             # prove round-trip + CRC on your file
    python replay_titles.py set <match_id> <title>   # set one title (real write)
"""

import glob
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import time
import zlib

_DAT_GLOB = r"C:\Program Files (x86)\Steam\userdata\*\570\remote\cfg\downloaded_replays_info.dat"

T_NESTED, T_STRING, T_INT32, T_FLOAT, T_UINT64, T_END = 0x00, 0x01, 0x02, 0x03, 0x07, 0x0B

# A node is a 3-tuple (key:str, type:int, value). For T_NESTED, value is a list of nodes.


def find_dat():
    """Path to the user's downloaded_replays_info.dat, or None."""
    hits = sorted(glob.glob(_DAT_GLOB))
    return hits[0] if hits else None


def _rcstr(data, p):
    e = data.index(b"\x00", p)
    return data[p:e].decode("utf-8", "replace"), e + 1


def _parse(data, p):
    """Parse a key block; return (nodes, pos, terminated_by_end_marker)."""
    out = []
    while p < len(data):
        t = data[p]
        p += 1
        if t == T_END:
            return out, p, True
        key, p = _rcstr(data, p)
        if t == T_NESTED:
            val, p, _ = _parse(data, p)
        elif t == T_STRING:
            val, p = _rcstr(data, p)
        elif t == T_INT32:
            val = struct.unpack_from("<i", data, p)[0]; p += 4
        elif t == T_FLOAT:
            val = struct.unpack_from("<f", data, p)[0]; p += 4
        elif t == T_UINT64:
            val = struct.unpack_from("<Q", data, p)[0]; p += 8
        else:
            raise ValueError(f"unknown VBKV type 0x{t:02x} at offset {p - 1}")
        out.append((key, t, val))
    return out, p, False


def parse_bytes(data):
    """Return (root_nodes, root_terminated). Validates the VBKV magic only."""
    if data[:4] != b"VBKV":
        raise ValueError("not a VBKV file (bad magic)")
    root, _end, term = _parse(data, 8)
    return root, term


def _serialize(nodes, terminate):
    out = bytearray()
    for key, t, val in nodes:
        out.append(t)
        out += key.encode("utf-8") + b"\x00"
        if t == T_NESTED:
            out += _serialize(val, True)
        elif t == T_STRING:
            out += val.encode("utf-8") + b"\x00"
        elif t == T_INT32:
            out += struct.pack("<i", val)
        elif t == T_FLOAT:
            out += struct.pack("<f", val)
        elif t == T_UINT64:
            out += struct.pack("<Q", val)
        else:
            raise ValueError(f"cannot serialize type 0x{t:02x} for key {key!r}")
    if terminate:
        out.append(T_END)
    return out


def build(root, term):
    """Serialize a parsed tree back to a full .dat byte string, CRC recomputed."""
    body = bytes(_serialize(root, term))
    crc = zlib.crc32(body) & 0xFFFFFFFF
    return b"VBKV" + struct.pack("<I", crc) + body


def crc_ok(data):
    """True if the stored CRC32 matches the body."""
    return data[4:8] == struct.pack("<I", zlib.crc32(data[8:]) & 0xFFFFFFFF)


def _downloads(root):
    # root == [("DownloadsInfo", T_NESTED, [entries...])]
    return root[0][2]


def _entry_match_id(body):
    for k, t, v in body:
        if k == "match" and t == T_NESTED:
            for kk, _tt, vv in v:
                if kk == "match_id":
                    return vv
    return None


def titles_from_bytes(data):
    """Map {match_id: title} for entries that have a custom name."""
    root, _ = parse_bytes(data)
    out = {}
    for _name, _t, body in _downloads(root):
        mid = _entry_match_id(body)
        for k, t, v in body:
            if k == "title" and t == T_STRING and v:
                if mid is not None:
                    out[mid] = v
    return out


def titles(path=None):
    """Map {match_id: title}. Read-only."""
    path = path or find_dat()
    if not path or not os.path.exists(path):
        raise FileNotFoundError(path or "downloaded_replays_info.dat not found")
    with open(path, "rb") as f:
        return titles_from_bytes(f.read())


def _next_download_index(downloads):
    """Next free 'downloadN' index, so created entries don't collide with Dota's."""
    mx = -1
    for name, _t, _b in downloads:
        if name.startswith("download"):
            try:
                mx = max(mx, int(name[8:]))
            except ValueError:
                pass
    return mx + 1


def _make_entry(name, match_id, title, meta):
    """A minimal but structurally faithful download entry. Dota enriches the match block
    (teams/heroes) from its game coordinator the next time it scans the folder; we only
    need a valid skeleton carrying match_id + the title, in Dota's field order."""
    match = [
        ("match_id", T_UINT64, int(match_id)),
        ("start_time", T_INT32, int(meta.get("start_time") or 0)),
        ("duration", T_INT32, int(meta.get("duration") or 0)),
        ("game_mode", T_INT32, int(meta.get("game_mode") or 0)),
        ("players", T_NESTED, []),
    ]
    body = [
        ("match", T_NESTED, match),
        ("title", T_STRING, title),
        ("size", T_INT32, int(meta.get("size") or 0)),
        ("exists_on_disk", T_INT32, 1),
    ]
    return (name, T_NESTED, body)


def _set_or_create(root, updates, create_missing=True):
    """Set `title` on existing entries; optionally create entries for unknown matches.
    `updates`: iterable of {match_id, title, size?, start_time?, duration?, game_mode?}.
    A new title node is inserted right after `match`, matching Dota's own layout.
    Returns {set:[mid], created:[mid], skipped_missing:[mid]}."""
    downloads = _downloads(root)
    index = {}
    for _n, _t, body in downloads:
        mid = _entry_match_id(body)
        if mid is not None:
            index[mid] = body
    nexti = _next_download_index(downloads)
    res = {"set": [], "created": [], "skipped_missing": []}
    for u in updates:
        mid = int(u["match_id"])
        title = u.get("title")
        if not title:
            continue
        body = index.get(mid)
        if body is not None:
            for j, (k, _t, _v) in enumerate(body):
                if k == "title":
                    body[j] = ("title", T_STRING, title)
                    break
            else:
                at = next((i + 1 for i, (k, *_r) in enumerate(body) if k == "match"), len(body))
                body.insert(at, ("title", T_STRING, title))
            res["set"].append(mid)
        elif create_missing:
            entry = _make_entry(f"download{nexti}", mid, title, u)
            downloads.append(entry)
            index[mid] = entry[2]
            nexti += 1
            res["created"].append(mid)
        else:
            res["skipped_missing"].append(mid)
    return res


def dota_running():
    """True if dota2.exe is currently running."""
    try:
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq dota2.exe", "/NH"],
            capture_output=True, text=True, timeout=10,
        ).stdout.lower()
        return "dota2.exe" in out
    except Exception:  # noqa: BLE001
        return False


def apply(updates, path=None, backup=True, allow_dota_running=False, create_missing=True):
    """Set titles on existing entries and (optionally) create entries for replays Dota
    hasn't indexed yet. `updates`: list of {match_id, title, size?, start_time?,
    duration?, game_mode?}.

    Safe: refuses while Dota runs (unless allow_dota_running), verifies the current file
    round-trips byte-exact (tripwire), keeps a .bak, writes atomically, recomputes CRC."""
    path = path or find_dat()
    if not path or not os.path.exists(path):
        raise FileNotFoundError(path or "downloaded_replays_info.dat not found")
    if dota_running() and not allow_dota_running:
        raise RuntimeError("Dota 2 is running. Close it first — it overwrites this file on exit.")

    with open(path, "rb") as f:
        data = f.read()
    root, term = parse_bytes(data)
    if build(root, term) != data:
        raise RuntimeError("refusing to write: this .dat does not round-trip byte-exact "
                           "(format may have changed); aborting to avoid corruption.")

    res = _set_or_create(root, updates, create_missing=create_missing)
    new = build(root, term)

    if backup:
        bak = path + ".bak"
        if not os.path.exists(bak):
            shutil.copy2(path, bak)
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(new)
    os.replace(tmp, path)

    with open(path, "rb") as f:
        check = f.read()
    res["crc_ok"] = crc_ok(check)
    res["backup"] = (path + ".bak") if backup else None
    res["verified"] = titles_from_bytes(check)
    return res


def write_titles(mapping, path=None, backup=True, allow_dota_running=False, create_missing=False):
    """Back-compat: set titles from {match_id: title}. By default does NOT create entries
    for unknown matches (pass create_missing=True, or use apply())."""
    updates = [{"match_id": int(k), "title": v} for k, v in mapping.items()]
    res = apply(updates, path=path, backup=backup,
                allow_dota_running=allow_dota_running, create_missing=create_missing)
    res["applied"] = {m: res["verified"].get(m) for m in (res["set"] + res["created"])}
    res["missing"] = res["skipped_missing"]
    return res


# --------------------------------------------------------------------------- CLI

def _snapshot(path):
    with open(path, "rb") as f:
        data = f.read()
    return hashlib.sha256(data).hexdigest(), titles_from_bytes(data)


def _cmd_dump():
    path = find_dat()
    if not path:
        print("downloaded_replays_info.dat not found", file=sys.stderr); return 1
    print(f"# {path}")
    print(json.dumps({str(k): v for k, v in titles(path).items()}, indent=2, ensure_ascii=False))
    return 0


def _cmd_selftest():
    path = find_dat()
    if not path:
        print("downloaded_replays_info.dat not found", file=sys.stderr); return 1
    with open(path, "rb") as f:
        data = f.read()
    root, term = parse_bytes(data)
    rebuilt = build(root, term)
    print(f"file:           {path}")
    print(f"size:           {len(data)} bytes")
    print(f"stored CRC ok:  {crc_ok(data)}")
    print(f"round-trip:     {'EXACT' if rebuilt == data else 'MISMATCH'}")
    print(f"entries:        {len(_downloads(root))}")
    print(f"titles:         {titles_from_bytes(data)}")
    return 0 if rebuilt == data and crc_ok(data) else 1


def _cmd_set(mid, title):
    try:
        res = write_titles({int(mid): title})
    except (RuntimeError, FileNotFoundError) as e:
        print(f"ERROR: {e}", file=sys.stderr); return 1
    print(json.dumps(res, indent=2, ensure_ascii=False))
    return 0 if res["applied"] and res["crc_ok"] else 1


def _diff(old, new):
    added = {k: new[k] for k in new if k not in old}
    removed = {k: old[k] for k in old if k not in new}
    changed = {k: (old[k], new[k]) for k in new if k in old and old[k] != new[k]}
    return added, removed, changed


def _cmd_watch(timeout):
    path = find_dat()
    if not path:
        print("downloaded_replays_info.dat not found", file=sys.stderr); return 1
    base_hash, base_titles = _snapshot(path)
    base_mtime = os.path.getmtime(path)
    print(f"Watching: {path}")
    print(f"Baseline: sha256={base_hash[:16]}...  titles={len(base_titles)}  "
          f"mtime={time.strftime('%H:%M:%S', time.localtime(base_mtime))}")
    print("Now rename a replay inside Dota 2. (If nothing shows up, fully EXIT Dota 2 -- "
          "Steam Cloud writes the remote\\ folder on game close.)")
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(2)
        try:
            cur_hash, cur_titles = _snapshot(path)
        except (OSError, ValueError):
            continue
        if cur_hash == base_hash:
            continue
        added, removed, changed = _diff(base_titles, cur_titles)
        print("\n*** FILE CHANGED ***")
        print(f"mtime: {time.strftime('%H:%M:%S', time.localtime(os.path.getmtime(path)))}  "
              f"sha256 {base_hash[:12]}... -> {cur_hash[:12]}...")
        for mid, t in added.items():
            print(f"  + ADDED   match {mid}: title = {t!r}")
        for mid, (a, b) in changed.items():
            print(f"  ~ CHANGED match {mid}: {a!r} -> {b!r}")
        for mid, t in removed.items():
            print(f"  - REMOVED match {mid}: was {t!r}")
        if not (added or removed or changed):
            print("  (bytes changed but no title field changed -- new download or metadata)")
        return 0
    print(f"\nNo change detected within {timeout}s.")
    return 2


def main(argv):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    cmd = argv[1] if len(argv) > 1 else "dump"
    if cmd == "dump":
        return _cmd_dump()
    if cmd == "selftest":
        return _cmd_selftest()
    if cmd == "watch":
        return _cmd_watch(int(argv[2]) if len(argv) > 2 else 900)
    if cmd == "set" and len(argv) >= 4:
        return _cmd_set(argv[2], " ".join(argv[3:]))
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
