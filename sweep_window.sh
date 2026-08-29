#!/usr/bin/env bash
# Wait for a LIVE onboarding window -- proven by a reply to the LR3 verb, not
# by the AP being visible -- then immediately sweep the command vocabulary.
#
# The AP keeps broadcasting and udp/2379 stays bound after the ~10 minute
# onboarding timer expires, but the responder goes silent. So AP presence and
# an open port are both useless as liveness signals. Only a reply counts.
set -uo pipefail
cd "$(dirname "$0")" || exit 1
mkdir -p captures
exec python3 sweep_window.py "$@" 2>&1 | tee "captures/sweep-$(date +%Y%m%d-%H%M%S).log"
