# Checklist para entrega C3.A2

- [x] Gateway, serviço de inferência, worker e vector store em serviços distintos.
- [x] Dockerfile individual para cada serviço próprio; Redis, Qdrant, collector e Caddy também conteinerizados.
- [x] Compose sobe conjunto local com um comando.
- [x] JWT gateway, proteção de jobs e rate limit.
- [x] Timeout, retries/backoff e circuit breaker.
- [x] Propagação de tracing gateway → fila → worker e export OTLP.
- [x] Seção README de LGPD, CAP, custo e latência.
- [ ] `docker compose up --build` validado em host com Docker.
- [ ] Deploy gratuito publicado e URL HTTPS real testada, adicionada ao README.
- [ ] Validar em clone limpo/segunda máquina.
- [ ] Confirmar políticas de retenção, segredo e autorização do provedor de IA.
