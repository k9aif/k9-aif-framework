#!/bin/bash
# K9-AIF App Generator (Unix launcher)
# Usage: ./gen.sh preview AppName
#        ./gen.sh run AppName

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

python -m k9_aif_generator.generator "$@"
