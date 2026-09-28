#!/bin/bash
# Part wavs -> tagged mp3s -> an AudiobookShelf library, as they finish rendering, then chapters.
#
#   publish.sh book.env
#
# book.env (see examples/book.env.example) sets BOOK, AUTHOR, PARTS (a TSV of "NN<TAB>Title"),
# WAV_DIR (local dir, or user@host:dir when the render box is elsewhere) and DEST (the book's
# folder inside the library, local or user@host:dir). Optional: YEAR, NARRATOR, COVER, DESC,
# ABS_URL + auth (see abs_tool.py), NTFY_TOPIC for phone pushes.
#
# Safe to rerun: parts already in DEST are skipped. Runs alongside a render: it waits for each
# part wav to exist and stop changing. Exits non-zero unless ABS chapters == tracks.
set -u
. "${1:?usage: publish.sh book.env}"
HERE=$(cd "$(dirname "$0")" && pwd)
: "${BOOK:?}" "${AUTHOR:?}" "${PARTS:?}" "${WAV_DIR:?}" "${DEST:?}"
NARRATOR=${NARRATOR:-}; YEAR=${YEAR:-}; NTFY_TOPIC=${NTFY_TOPIC:-}; ABS_URL=${ABS_URL:-}
WORK=$(mktemp -d); trap 'rm -rf "$WORK"' EXIT

remote() { [[ "$1" == *:* && "$1" != [A-Za-z]:* ]]; }          # user@host:path (not C:/...)
run_at() { if remote "$1"; then ssh -n -o BatchMode=yes "${1%%:*}" "$2"; else bash -c "$2" </dev/null; fi; }   # -n: don't eat the PARTS loop's stdin
path_of() { if remote "$1"; then echo "${1#*:}"; else echo "$1"; fi; }
copy() { if remote "$1" || remote "$2"; then scp -q "$1" "$2" </dev/null; else cp "$1" "$2"; fi; }
note() { [ -n "$NTFY_TOPIC" ] && curl -s -H "Title: $1" -H "Tags: ${3:-headphones}" -d "$2" "https://ntfy.sh/$NTFY_TOPIC" >/dev/null; true; }
abs() { [ -n "$ABS_URL" ] && python3 "$HERE/abs_tool.py" "$@" </dev/null; }

run_at "$DEST" "mkdir -p '$(path_of "$DEST")'"
for f in ${COVER:-} ${DESC:-}; do [ -f "$f" ] && copy "$f" "$DEST/"; done
[ -n "$NARRATOR" ] && echo "$NARRATOR" > "$WORK/reader.txt" && copy "$WORK/reader.txt" "$DEST/"

first=1
while IFS=$'\t' read -r n T; do
  [ -z "$n" ] && continue
  f="$n - ${T%%:*}.mp3"; f=${f//\//-}
  run_at "$DEST" "test -s '$(path_of "$DEST")/$f'" && continue
  w="$(path_of "$WAV_DIR")/$n.wav"
  until run_at "$WAV_DIR" "test -s '$w' && [ \$(( \$(date +%s) - \$(stat -c %Y '$w') )) -gt 20 ]"; do sleep 60; done
  copy "$WAV_DIR/$n.wav" "$WORK/$n.wav" || continue
  ffmpeg -nostdin -y -loglevel error -i "$WORK/$n.wav" -af loudnorm=I=-20:TP=-1.5:LRA=11 -ac 1 -ar 24000 -b:a 64k \
    -id3v2_version 3 -metadata title="$T" -metadata track="$((10#$n + 1))" -metadata album="$BOOK" \
    -metadata artist="$AUTHOR" -metadata album_artist="$AUTHOR" -metadata composer="$NARRATOR" \
    -metadata genre=Audiobook ${YEAR:+-metadata date="$YEAR"} "$WORK/$f" || continue
  copy "$WORK/$f" "$DEST/" && rm -f "$WORK/$n.wav" "$WORK/$f"
  abs scan >/dev/null 2>&1
  echo "$(date +%H:%M) published $f"
  [ $first = 1 ] && first=0 && note "$BOOK: first part live" "More parts will follow as they render."
done < "$PARTS"

[ -z "$ABS_URL" ] && { echo "ALL_DONE (no ABS_URL: skipped chapter check)"; exit 0; }
sleep 20; abs scan >/dev/null 2>&1; sleep 20
abs chapters "$BOOK" || { note "$BOOK: chapters FAILED" "Tracks are up but the chapter list is wrong." warning; exit 1; }
note "$BOOK complete" "All parts published with chapters." "tada,headphones"
echo ALL_DONE
