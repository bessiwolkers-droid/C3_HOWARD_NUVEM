# Operação e desenvolvimento

Inserção de documento de teste no Qdrant (a API vectorstore não é publicada para fora por padrão):

```bash
docker compose exec inference python -c "import httpx; print(httpx.post('http://vectorstore:8002/documents', json={'id':'cap-01','text':'O teorema CAP trata de consistência, disponibilidade e tolerância a partições.'}, timeout=5).json())"
```

Para consultar um job, use o `job_id` devolvido pelo gateway. O campo `status` transita `queued`, `retrying`, `completed` ou `failed`. Para inspecionar tracing: `docker compose logs -f otel-collector`. Não habilite logs de corpo HTTP em ambiente público.
