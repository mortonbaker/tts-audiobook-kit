#!/usr/bin/env python3
"""AudiobookShelf helpers for a book that lands one file at a time.

    abs_tool.py scan [--library NAME --folder PATH]   create the library if missing, then scan it
    abs_tool.py chapters "Book Title" [--dry]          one chapter per audio track, verified
    abs_tool.py chapters --id <libraryItemId> [--dry]

Why `chapters` exists: ABS builds an item's chapter list once, when it first creates the item.
A render that publishes chapter by chapter creates the item after track 1 or 2, so every later
track shows under Audio Tracks while chapter navigation dead-ends. Rescans do not fix it (ABS
treats chapters as user-edited metadata). This rebuilds them from the tracks' durations, titled
from each file's ID3 title, and exits non-zero unless chapters == tracks.

Auth, first match wins: ABS_TOKEN; ABS_USER + ABS_PASSWORD; ABS_CREDS=<file with user=... and
password=... lines>. Server: ABS_URL (default http://127.0.0.1:13378).
"""
import json
import os
import re
import sys
import urllib.request

ABS = os.environ.get("ABS_URL", "http://127.0.0.1:13378").rstrip("/")


def api(path, token=None, data=None, method=None):
    req = urllib.request.Request(
        ABS + path,
        data=json.dumps(data).encode() if data is not None else None,
        method=method or ("POST" if data is not None else "GET"),
        headers={"Content-Type": "application/json", **({"Authorization": "Bearer " + token} if token else {})})
    with urllib.request.urlopen(req, timeout=30) as r:
        body = r.read()
    try:                               # /scan answers 200 with a non-JSON body
        return json.loads(body) if body else {}
    except json.JSONDecodeError:
        return {"raw": body.decode(errors="replace")}


def login():
    if os.environ.get("ABS_TOKEN"):
        return os.environ["ABS_TOKEN"]
    user, pw = os.environ.get("ABS_USER"), os.environ.get("ABS_PASSWORD")
    if not (user and pw) and os.environ.get("ABS_CREDS"):
        text = open(os.path.expanduser(os.environ["ABS_CREDS"])).read()
        user = re.search(r"user[^=:]*[=:]\s*(\S+)", text, re.I).group(1)
        pw = re.search(r"pass[^=:]*[=:]\s*(\S+)", text, re.I).group(1)
    if not (user and pw):
        sys.exit("set ABS_TOKEN, or ABS_USER + ABS_PASSWORD, or ABS_CREDS")
    return api("/login", data={"username": user, "password": pw})["user"]["token"]


def scan(token, name, folder):
    libs = api("/api/libraries", token)["libraries"]
    lib = next((l["id"] for l in libs if l["name"] == name), None)
    if not lib:
        if not folder:
            sys.exit(f"no library {name!r}; pass --folder to create it")
        lib = api("/api/libraries", token, data={
            "name": name, "folders": [{"fullPath": folder}], "mediaType": "book",
            "provider": "google", "settings": {"disableWatcher": True}})["id"]
        print("created library", lib)
    api(f"/api/libraries/{lib}/scan", token, data={})
    print("scan requested:", name)


def find_item(token, title):
    for lib in api("/api/libraries", token)["libraries"]:
        for it in api(f"/api/libraries/{lib['id']}/items", token)["results"]:
            if it["media"]["metadata"].get("title", "").lower() == title.lower():
                return it["id"]
    sys.exit(f"no library item titled {title!r}")


def track_title(af, n):
    tag = (af.get("metaTags") or {}).get("tagTitle")
    if tag:
        return tag
    stem = os.path.splitext(af["metadata"]["filename"])[0]
    return re.sub(r"^\d+\s*[-_.]\s*", "", stem) or f"Track {n}"


def chapters(token, item_id, dry):
    item = api(f"/api/items/{item_id}?expanded=1", token)
    files = sorted(item["media"]["audioFiles"], key=lambda a: a["index"])
    have = item["media"].get("chapters", [])
    want, start = [], 0.0
    for n, af in enumerate(files):
        end = start + af["duration"]
        want.append({"id": n, "start": round(start, 3), "end": round(end, 3), "title": track_title(af, n)})
        start = end
    print(f"{item['media']['metadata']['title']}: {len(files)} tracks, {len(have)} chapters -> {len(want)} chapters")
    for c in want:
        print(f"  {c['id']:>3}  {c['start'] / 60:7.1f}m  {c['title']}")
    if dry:
        return
    if have != want:
        api(f"/api/items/{item_id}/chapters", token, data={"chapters": want})
    after = api(f"/api/items/{item_id}?expanded=1", token)["media"]
    n_ch, n_tr = len(after.get("chapters", [])), len(after["audioFiles"])
    if n_ch != n_tr:
        sys.exit(f"FAILED: {n_ch} chapters for {n_tr} tracks")
    print(f"OK: {n_ch} chapters == {n_tr} tracks")


def opt(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("scan", "chapters"):
        sys.exit(__doc__)
    token = login()
    if sys.argv[1] == "scan":
        scan(token, opt("--library", os.environ.get("ABS_LIBRARY", "Narrated")), opt("--folder", os.environ.get("ABS_FOLDER")))
    else:
        pos = [a for a in sys.argv[2:] if not a.startswith("--") and a != opt("--id")]
        chapters(token, opt("--id") or find_item(token, pos[0]), "--dry" in sys.argv)


if __name__ == "__main__":
    main()
