#!/bin/bash

. ./bin/utils.sh --source-only

log "creating patch version"
npm version patch

log "generating changelog"
pnpm changelog

CURRENT_TAG=$(git describe)

log "current tag: $CURRENT_TAG"

git tag -d $CURRENT_TAG

log "updating all apps and libraries with tag version $CURRENT_TAG"
pnpm version:patch

log "squashing commits"
git add -A
git cm -n --no-edit

git tag $CURRENT_TAG
