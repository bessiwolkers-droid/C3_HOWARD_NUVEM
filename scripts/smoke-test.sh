#!/usr/bin/env bash
# Testa o fluxo completo com a stack no ar (docker compose up --build -d):
# login -> envio do job -> worker -> inferencia -> vectorstore -> resultado,
# e confere se o mesmo trace aparece no gateway e no worker.
set -euo pipefail
cd "$(dirname "$0")/.."

BASE=${BASE_URL:-http://localhost:8000}
PY=$(command -v python3 || command -v python)
json() { "$PY" -c "import json,sys; print(json.load(sys.stdin)$1)"; }
env_value() { grep -E "^$1=" .env | tail -1 | cut -d= -f2- | tr -d '\r'; }

echo "Aguardando os servicos..."
for i in $(seq 1 60); do
  if curl -fs "$BASE/saude" >/dev/null \
    && docker compose exec -T inference python -c "import urllib.request; urllib.request.urlopen('http://localhost:8001/saude')" 2>/dev/null \
    && docker compose exec -T vectorstore python -c "import urllib.request; urllib.request.urlopen('http://localhost:8002/saude')" 2>/dev/null; then
    break
  fi
  [ "$i" -eq 60 ] && { echo "Servicos nao ficaram prontos"; exit 1; }
  sleep 2
done

echo "Login..."
USER_NAME=$(env_value DEMO_USERNAME); USER_NAME=${USER_NAME:-aluno}
LOGIN=$("$PY" -c "import json,sys; print(json.dumps({'username':sys.argv[1],'password':sys.argv[2]}))" "$USER_NAME" "$(env_value DEMO_PASSWORD)")
TOKEN=$(curl -fs -X POST "$BASE/auth/login" -H 'Content-Type: application/json' -d "$LOGIN" | json "['access_token']")

echo "Sem token deve dar 401..."
[ "$(curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE/v1/jobs" -H 'Content-Type: application/json' -d '{"text":"x"}')" = 401 ]

echo "Enviando job..."
JOB=$(curl -fs -X POST "$BASE/v1/jobs" -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"text":"Explique o teorema CAP"}' | json "['job_id']")
echo "job_id=$JOB"

for i in $(seq 1 45); do
  RESP=$(curl -fs "$BASE/v1/jobs/$JOB" -H "Authorization: Bearer $TOKEN")
  STATUS=$(echo "$RESP" | json "['status']")
  [ "$STATUS" = completed ] && break
  [ "$STATUS" = failed ] && { echo "$RESP"; exit 1; }
  sleep 2
done
[ "$STATUS" = completed ] || { echo "Job nao terminou: $RESP"; exit 1; }
echo "$RESP"

echo "Conferindo o trace gateway -> fila -> worker..."
sleep 8
docker compose logs --no-log-prefix otel-collector | awk '
  /service.name: Str\(/ { match($0, /Str\([^)]*\)/); svc = substr($0, RSTART + 4, RLENGTH - 5) }
  /Trace ID *:/ { print svc, $NF }' | sort -u > /tmp/c3-traces.txt
COMUNS=$(comm -12 <(awk '$1=="gateway"{print $2}' /tmp/c3-traces.txt | sort -u) \
                  <(awk '$1=="queue-worker"{print $2}' /tmp/c3-traces.txt | sort -u) | wc -l)
[ "$COMUNS" -gt 0 ] || { echo "Nenhum trace em comum entre gateway e worker"; exit 1; }
echo "OK: $COMUNS trace(s) passam pelo gateway e pelo worker."
