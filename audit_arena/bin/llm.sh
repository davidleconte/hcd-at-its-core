#!/usr/bin/env bash
# Mode B adapter — route an arena role to an EXTERNAL model family so no single family
# grades its own work. Provider-agnostic and KEY-GATED: if the needed API key is absent,
# it exits 2 with a clear message and the orchestrator falls back to Mode A (subagent).
#
# Usage:   bin/llm.sh <role> <prompt_file>      # role = defender | judge
# Config (env, with defaults; put keys in ~/.secrets.env):
#   ARENA_DEFENDER_PROVIDER  default: glm     (needs ZAI_API_KEY)
#   ARENA_JUDGE_PROVIDER     default: gemini  (needs GEMINI_API_KEY)
#   Providers: glm (z.ai) | gemini (google) | openai (OpenAI-compatible; needs
#              OPENAI_API_KEY and optional OPENAI_BASE_URL + OPENAI_MODEL)
set -euo pipefail
# shellcheck source=/dev/null
source ~/.secrets.env 2>/dev/null || true

ROLE="${1:?usage: llm.sh <defender|judge> <prompt_file>}"
PROMPT_FILE="${2:?missing prompt file}"
[ -f "$PROMPT_FILE" ] || { echo "no such prompt file: $PROMPT_FILE" >&2; exit 1; }

# Egress guard — Mode B sends repo excerpts (findings + cited source) to a third-party LLM.
# That is a deliberate act, not an ambient side effect of a key being in the shell. Require
# explicit per-run opt-in; otherwise exit 2 so the orchestrator falls back to Mode A (subagent).
if [ "${ARENA_MODE_B:-0}" != "1" ]; then
  echo "[mode-B] disabled — external LLM calls would send repo excerpts off-machine." >&2
  echo "[mode-B] Re-run with ARENA_MODE_B=1 to opt in; falling back to Mode A (subagent)." >&2
  exit 2
fi

case "$ROLE" in
  defender) PROVIDER="${ARENA_DEFENDER_PROVIDER:-glm}" ;;
  judge)    PROVIDER="${ARENA_JUDGE_PROVIDER:-gemini}" ;;
  *)        PROVIDER="${ARENA_PROVIDER:-$ROLE}" ;;   # allow direct provider name
esac

need() { # need KEYVAR -> exit 2 if absent (Mode B unavailable; use Mode A)
  if [ -z "${!1:-}" ]; then
    echo "[mode-B] $1 not set — external $ROLE ($PROVIDER) unavailable; use Mode A (subagent)." >&2
    exit 2
  fi
}

case "$PROVIDER" in
  glm)
    need ZAI_API_KEY
    python3 - "$ZAI_API_KEY" "$PROMPT_FILE" <<'PY'
import sys, json, urllib.request
key, pf = sys.argv[1], sys.argv[2]
body = json.dumps({"model": "glm-4.6",
    "messages": [{"role": "user", "content": open(pf, encoding="utf-8").read()}],
    "temperature": 0.2, "max_tokens": 32000}).encode()
req = urllib.request.Request("https://api.z.ai/api/paas/v4/chat/completions", data=body,
    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
with urllib.request.urlopen(req, timeout=600) as r:
    print((json.load(r)["choices"][0]["message"].get("content") or "").strip())
PY
    ;;
  gemini)
    need GEMINI_API_KEY
    python3 - "$GEMINI_API_KEY" "$PROMPT_FILE" <<'PY'
import sys, json, urllib.request
key, pf = sys.argv[1], sys.argv[2]
body = json.dumps({"contents": [{"parts": [{"text": open(pf, encoding="utf-8").read()}]}],
    "generationConfig": {"temperature": 0.2, "maxOutputTokens": 16384}}).encode()
url = ("https://generativelanguage.googleapis.com/v1beta/models/"
       "gemini-2.5-pro:generateContent?key=" + key)
req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
with urllib.request.urlopen(req, timeout=600) as r:
    d = json.load(r)
print("".join(p.get("text", "") for p in d["candidates"][0]["content"]["parts"]))
PY
    ;;
  openai)
    need OPENAI_API_KEY
    python3 - "$OPENAI_API_KEY" "$PROMPT_FILE" <<'PY'
import sys, os, json, urllib.request
key, pf = sys.argv[1], sys.argv[2]
base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
model = os.environ.get("OPENAI_MODEL", "gpt-4.1")
body = json.dumps({"model": model, "temperature": 0.2,
    "messages": [{"role": "user", "content": open(pf, encoding="utf-8").read()}]}).encode()
req = urllib.request.Request(base + "/chat/completions", data=body,
    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
with urllib.request.urlopen(req, timeout=600) as r:
    print((json.load(r)["choices"][0]["message"].get("content") or "").strip())
PY
    ;;
  *)
    echo "[mode-B] unknown provider '$PROVIDER' for role $ROLE" >&2; exit 1 ;;
esac
