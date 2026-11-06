#!/usr/bin/env bash
# Dev-only: capture real help and man text from the programs installed on this machine,
# so the parsers can be tested offline. Writes plain text only (no .gz: catalog rule 17).
# Usage: scripts/capture_fixtures.sh   (run from the repo root)
set -u
OUT="tests/fixtures/help"
mkdir -p "$OUT"
SCRATCH="$(mktemp -d)"
trap 'rm -rf "$SCRATCH"' EXIT

# Same safe environment fluent uses when it reads help: no pager, no color, C locale,
# empty working directory, no stdin.
run() {
  local dest="$1"; shift
  mkdir -p "$(dirname "$OUT/$dest")"
  (cd "$SCRATCH" && env -i PATH="$PATH" HOME="$SCRATCH" LANG=C LC_ALL=C NO_COLOR=1 \
     PAGER=cat GIT_PAGER=cat MANPAGER=cat TERM=dumb timeout 10 "$@" </dev/null) \
     >"$OUT/$dest" 2>&1
  echo "$(wc -l <"$OUT/$dest") lines  $dest"
}

man_text() {  # decompress a man page (roff source) to plain text
  local page="$1" dest="$2" f
  f="$(man -w "$page" 2>/dev/null)" || { echo "no man page: $page"; return; }
  mkdir -p "$(dirname "$OUT/$dest")"
  case "$f" in *.gz) gzip -dc "$f" >"$OUT/$dest" ;; *) cat "$f" >"$OUT/$dest" ;; esac
  echo "$(wc -l <"$OUT/$dest") lines  $dest"
}

# git: root help, subcommand -h (exit 129 is normal), a few man pages
run git/version.txt git --version
run git/root.txt git --help
for s in add branch checkout clean clone commit diff fetch log merge mv pull push rebase \
         remote reset restore rm stash status switch tag; do
  run "git/$s.txt" git "$s" -h
done
for p in git git-log git-push git-reset git-clean; do man_text "$p" "git/man/$p.1"; done

# gh (cobra)
run gh/version.txt gh --version
run gh/root.txt gh --help
for s in "repo" "repo delete" "repo list" "repo clone" "pr" "pr create" "pr list" "pr merge" \
         "issue" "issue list" "issue create" "release" "release delete" "api"; do
  run "gh/${s// /_}.txt" gh $s --help
done
man_text gh-repo-delete gh/man/gh-repo-delete.1

# docker (cobra)
run docker/version.txt docker --version
run docker/root.txt docker --help
for s in "ps" "run" "images" "image" "image prune" "image ls" "rm" "rmi" "logs" "exec" "build" \
         "system" "system prune" "volume" "volume rm" "container" "container prune"; do
  run "docker/${s// /_}.txt" docker $s --help
done
man_text docker-run docker/man/docker-run.1

# ffmpeg: short help and full help (options like -crf only appear in -h full)
run ffmpeg/version.txt ffmpeg -hide_banner -version
run ffmpeg/short.txt ffmpeg -hide_banner -h
run ffmpeg/full.txt ffmpeg -hide_banner -h full
man_text ffmpeg ffmpeg/man/ffmpeg.1

# curl: --help is partial, --help all is complete
run curl/version.txt curl --version
run curl/short.txt curl --help
run curl/all.txt curl --help all
man_text curl curl/man/curl.1

# GNU tar, jq, rsync
run tar/version.txt tar --version
run tar/root.txt tar --help
man_text tar tar/man/tar.1
run jq/version.txt jq --version
run jq/root.txt jq --help
man_text jq jq/man/jq.1
run rsync/version.txt rsync --version
run rsync/root.txt rsync --help
man_text rsync rsync/man/rsync.1
