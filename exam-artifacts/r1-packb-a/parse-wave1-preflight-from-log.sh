#!/usr/bin/env bash
# Emit wave-1 preflight lines from the first R1-A2 start block in the run log (Claude resume ruling).
set -euo pipefail
LOG="${1:?log path}"
awk '
  /^=== R1-A2 pack B run start/ { block++ }
  block == 1 && /^sysprompt_chars=/ { print; c++ }
  block == 1 && /^sysprompt_sha256=/ { print; c++ }
  block == 1 && /^model_object=/ { print; c++ }
  block == 1 && /^preflight_ok$/ { print; exit }
  END { if (c != 3) exit 2 }
' "$LOG"
