#!/bin/sh
# zpf-web's Ignored Build Step (web/vercel.json's ignoreCommand). Vercel runs
# it inside web/ (the Root Directory): exit 0 skips the build, anything else
# builds. Whenever this script cannot tell, it builds -- an extra build costs
# minutes, a skipped preview of a real web/ change costs a reviewer the page.
#
# Production (main) is judged as it was on 2026-09-22: did web/ change between
# the last deployment that built (VERCEL_GIT_PREVIOUS_SHA) and HEAD, falling
# back to HEAD^.
#
# Any other branch is judged against main: did web/ change between the merge
# base with main and HEAD -- "does this branch change web/?". The production
# rule under-built here (PR #182, 2026-10-08): on a branch's first push
# VERCEL_GIT_PREVIOUS_SHA is unset, so it diffed HEAD^..HEAD, and when that tip
# was a merge FROM main, HEAD^ held the branch's own web/ change and the diff
# saw only main's commits, none under web/. Vercel clones with --depth=10, so
# main is fetched and both histories deepened until the merge base shows.

set -u

PRODUCTION_BRANCH=main
DEPTHS="64 256 1024"

# never wait on a credential prompt; a fetch that stalls is a fetch that failed
GIT_TERMINAL_PROMPT=0
export GIT_TERMINAL_PROMPT

say() { echo "vercel-ignore: $*"; }
build() { say "build: $*"; exit 1; }
skip() { say "skip: $*"; exit 0; }

top=$(git rev-parse --show-toplevel 2>/dev/null) || build "not a git checkout"
cd "$top" || build "cannot enter $top"
git rev-parse --verify --quiet 'HEAD^{commit}' >/dev/null || build "no HEAD commit"

# compare <rev> <label>: skip when web/ is the same at <rev> and HEAD.
compare() {
  git diff --quiet "$1" HEAD -- web
  case $? in
    0) skip "nothing under web/ changed since $2" ;;
    1) build "web/ changed since $2" ;;
    *) build "git could not diff against $2" ;;
  esac
}

ref=${VERCEL_GIT_COMMIT_REF:-}
if [ "${VERCEL_ENV:-}" = production ] || [ "$ref" = "$PRODUCTION_BRANCH" ]; then
  if [ -n "${VERCEL_GIT_PREVIOUS_SHA:-}" ]; then
    compare "$VERCEL_GIT_PREVIOUS_SHA" "the last built deployment ($VERCEL_GIT_PREVIOUS_SHA)"
  fi
  compare 'HEAD^' "HEAD^ (no previous deployment)"
fi

# Where main comes from: the clone's own remote, else the public GitHub URL
# Vercel's variables name (the repository is public).
remotes=""
git remote get-url origin >/dev/null 2>&1 && remotes=origin
if [ "${VERCEL_GIT_PROVIDER:-}" = github ] && [ -n "${VERCEL_GIT_REPO_OWNER:-}" ] \
  && [ -n "${VERCEL_GIT_REPO_SLUG:-}" ]; then
  remotes="$remotes https://github.com/$VERCEL_GIT_REPO_OWNER/$VERCEL_GIT_REPO_SLUG.git"
fi
[ -n "$remotes" ] || build "no remote to fetch $PRODUCTION_BRANCH from"

# fetch <depth>: main at that depth and, when the branch is known, the branch
# too -- a deeper fetch of HEAD's own branch is what deepens HEAD's history.
fetch() {
  for remote in $remotes; do
    if git -c http.lowSpeedLimit=1000 -c http.lowSpeedTime=30 fetch --quiet \
      --no-tags --depth="$1" "$remote" \
      "+refs/heads/$PRODUCTION_BRANCH:refs/vercel-ignore/$PRODUCTION_BRANCH"; then
      if [ -n "$ref" ]; then
        git -c http.lowSpeedLimit=1000 -c http.lowSpeedTime=30 fetch --quiet \
          --no-tags --depth="$1" "$remote" "+refs/heads/$ref:refs/vercel-ignore/branch" \
          || say "could not deepen $ref from $remote"
      fi
      return 0
    fi
  done
  return 1
}

for depth in $DEPTHS; do
  fetch "$depth" || build "could not fetch $PRODUCTION_BRANCH"
  if fork=$(git merge-base "refs/vercel-ignore/$PRODUCTION_BRANCH" HEAD 2>/dev/null); then
    compare "$fork" "the merge base with $PRODUCTION_BRANCH ($(git rev-parse --short "$fork"))"
  fi
  say "no merge base with $PRODUCTION_BRANCH at depth $depth"
done
build "no merge base with $PRODUCTION_BRANCH within $depth commits"
