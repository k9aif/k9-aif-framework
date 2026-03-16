#!/bin/bash
# K9-AIF App Generator (Unix launcher)

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

python generator/k9_generator.py "$@"
