#!/bin/bash

. ~/bin/utils.sh --source-only

git fetch -p

git --no-pager log --decorate --oneline -n 10
