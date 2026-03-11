#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "Usage: $0 <base_url> <bearer_token> [--insecure] [--with-actuation]"
  echo "Example: $0 https://192.168.59.202:8099 mytoken --insecure"
  exit 1
fi

BASE_URL="$1"
TOKEN="$2"
INSECURE="false"
WITH_ACTUATION="false"

for arg in "${@:3}"; do
  case "$arg" in
    --insecure) INSECURE="true" ;;
    --with-actuation) WITH_ACTUATION="true" ;;
    *)
      echo "Unknown option: $arg"
      exit 1
      ;;
  esac
done

CURL_FLAGS=(--silent --show-error --fail --connect-timeout 4 --max-time 10)
if [[ "$INSECURE" == "true" ]]; then
  CURL_FLAGS+=(--insecure)
fi

api_get() {
  local path="$1"
  curl "${CURL_FLAGS[@]}" \
    -H "Authorization: Bearer ${TOKEN}" \
    "${BASE_URL}${path}"
}

api_post() {
  local path="$1"
  local data="${2:-{}}"
  curl "${CURL_FLAGS[@]}" \
    -X POST \
    -H "Authorization: Bearer ${TOKEN}" \
    -H "Content-Type: application/json" \
    -d "${data}" \
    "${BASE_URL}${path}"
}

pretty_print() {
  if command -v jq >/dev/null 2>&1; then
    jq .
  else
    cat
  fi
}

echo "[1/9] Health (sin auth)"
curl "${CURL_FLAGS[@]}" "${BASE_URL}/health" | pretty_print

echo "[2/9] Version"
api_get "/v1/version" | pretty_print

echo "[3/9] Capabilities"
api_get "/v1/capabilities" | pretty_print

echo "[4/9] Sensors"
api_get "/v1/sensors" | pretty_print

echo "[5/9] Update status"
api_get "/v1/update/status" | pretty_print

echo "[6/9] App policy status (read-only)"
api_post "/v1/actuators/app_policy/status" "{}" | pretty_print

echo "[7/9] Session status (read-only)"
api_post "/v1/actuators/session_manager/status" "{}" | pretty_print

echo "[8/9] Verificacion auth negativa (debe fallar con 401)"
set +e
HTTP_CODE=$(curl "${CURL_FLAGS[@]}" -o /dev/null -w "%{http_code}" "${BASE_URL}/v1/capabilities")
set -e
if [[ "$HTTP_CODE" == "401" ]]; then
  echo "OK: sin token devuelve 401"
else
  echo "WARN: esperado 401 y devolvio ${HTTP_CODE}"
fi

if [[ "$WITH_ACTUATION" == "true" ]]; then
  echo "[9/9] Actuacion controlada: terminate"
  api_post "/v1/actuators/session_manager/terminate" "{}" | pretty_print
else
  echo "[9/9] Actuacion omitida (modo no intrusivo)"
fi
