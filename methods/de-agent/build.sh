#!/usr/bin/env bash
set -e
export SKIP_PLAYWRIGHT_INSTALL=1
poetry build -v
