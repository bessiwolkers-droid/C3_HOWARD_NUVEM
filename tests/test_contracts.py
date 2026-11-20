from pathlib import Path
import ast
import re
ROOT=Path(__file__).resolve().parents[1]
def test_each_application_service_has_dockerfile_and_requirements():
 for name in ('gateway','inference','worker','vectorstore'):
  p=ROOT/'services'/name
  assert (p/'Dockerfile').is_file() and (p/'requirements.txt').is_file()
  assert (p/('worker.py' if name=='worker' else 'app.py')).is_file()
def test_gateway_auth_and_routes_present():
 s=(ROOT/'services/gateway/app.py').read_text()
 for item in ("/auth/login","/v1/jobs","/v1/jobs/{job_id}","JWT_SECRET","Rate limit"):
  assert item in s
def test_worker_retry_and_backoff_present():
 s=(ROOT/'services/worker/worker.py').read_text()
 assert 'MAX_RETRIES' in s and 'class Breaker' in s
 assert re.search(r'asyncio\.sleep\(\s*min\(\s*2\s*\*\*\s*attempt\s*,\s*8\s*\)\s*\)',s)
def test_compose_includes_required_components_and_unique_builds():
 s=(ROOT/'docker-compose.yml').read_text()
 for item in ('gateway:','inference:','worker:','vectorstore:','redis:','qdrant:','otel-collector:','build: ./services/'):
  assert item in s
def test_sources_parse():
 for f in (ROOT/'services').glob('**/*.py'): ast.parse(f.read_text())
