# C3_HOWARD_NUVEM — Plataforma de IA como Serviço

Projeto integrador C3.A2 (FAESA, 2026/2), baseado nas experiências dos repositórios `HOWARD_NUVEM` (aulas de fila, worker, IA e resiliência) e `C2_HOWARD_NUVEM` (RAG/serviços), e estudando o kit oficial `sd-2026-2-kit-c3a2`. Autoria em grupo conforme o C2: Bernardo D'Angelo Leitão, Maria Isabel de Campos Rocha, José Henrique Bessi Wolkers e George Pinheiro Ramos.

> **Estado de entrega:** a implementação local e a configuração Docker estão preparadas. Este ambiente não tem Docker instalado, portanto a inicialização integrada ainda precisa ser executada em uma máquina com Docker. Nenhum deploy público foi criado: informe a URL real aqui somente depois de publicar e testar HTTPS. **URL pública: pendente de deploy.**

## Arquitetura

```mermaid
flowchart LR
 C[Cliente] -->|HTTPS / JWT| GW[API Gateway :8000]
 GW -->|publica job + trace context| R[(Redis fila + estado)]
 R --> W[Worker de fila]
 W -->|timeout/retry/backoff/circuit breaker| I[Inferência :8001]
 I --> V[Vector Store API :8002]
 V --> Q[(Qdrant)]
 GW -. OTLP .-> O[OpenTelemetry Collector]
 W -. OTLP .-> O
 I -. OTLP .-> O
 V -. OTLP .-> O
````

Gateway autentica e limita chamadas; jobs são assíncronos. Worker chama serviço de inferência, que recupera contexto pelo serviço de armazenamento vetorial Qdrant e opcionalmente chama uma API de IA externa. Sem `OPENAI_API_KEY`, o caminho offline segue funcional para demonstração. Os serviços próprios têm Dockerfile individual. Redis, Qdrant, collector e proxy HTTPS são containers de imagens oficiais.

## Rodar tudo localmente em Docker

Requisitos: Docker Engine/Desktop recente e Docker Compose v2. A partir da raiz do repositório:

```bash
cp .env.example .env
# Gere os segredos e edite .env (nunca comite o .env)
python -c "import secrets; print(secrets.token_urlsafe(48))"
# coloque o valor em JWT_SECRET e defina DEMO_PASSWORD
docker compose up --build -d
docker compose ps
```

Tudo sobe com um comando Compose. Gateway: `http://localhost:8000`; documentação: `/docs`. Health: `GET /saude`. Para a primeira demonstração, adicione documentos ao Qdrant via endpoint interno (temporariamente exponha o vectorstore no compose para desenvolvimento, ou use `docker compose exec` com cliente Python; veja `docs/OPERACAO.md`). Pode também enviar uma pergunta sem fontes para validar o fluxo em modo offline.

```bash
# Login (substitua senha pela que você colocou no .env)
curl -s http://localhost:8000/auth/login -H 'Content-Type: application/json' \
  -d '{"username":"aluno","password":"SUA_SENHA"}'
# copie access_token da resposta
curl -X POST http://localhost:8000/v1/jobs -H 'Authorization: Bearer TOKEN' \
  -H 'Content-Type: application/json' -d '{"text":"Explique o teorema CAP"}'
# consulte /v1/jobs/{job_id} com o mesmo token até completed ou failed
```

`OPENAI_API_KEY` é opcional; ao defini-la, a inferência externa é chamada através do endpoint OpenAI-compatible configurado por ambiente. Nenhum modelo é treinado. Operação: `docker compose logs -f gateway worker inference vectorstore`; parar: `docker compose down`; dados Redis/Qdrant persistem nos volumes nomeados. Remoção irreversível dos dados: `docker compose down -v`.

## API

- `POST /auth/login` — credenciais de demonstração definidas em ambiente; devolve JWT assinado HS256 com expiração.
- `GET /saude` — liveness público.
- `POST /v1/jobs` — bearer JWT obrigatório; body `{"text":"..."}`, responde 202 com `job_id`. Limitado a 60 chamadas/minuto por IP no processo gateway.
- `GET /v1/jobs/{job_id}` — bearer JWT obrigatório; somente o proprietário pode ver o estado/resultado.
- Serviço de inferência, worker, vetor e Qdrant não publicam portas no host.

## Resiliência e observabilidade

Chamadas HTTP do worker usam timeout de 20 s (conexão 3 s), no máximo quatro tentativas e espera exponencial limitada (1, 2, 4 s). Circuit breaker abre após cinco falhas, bloqueia chamadas por 20 s e então permite nova tentativa. Estados de jobs ficam no Redis; failures não expõem conteúdo de exceção ao cliente. Tracing OpenTelemetry exporta spans OTLP para gateway, publicação/consumo da fila (trace context propagado), worker e chamadas subsequentes. Collector exibe spans em log (`docker compose logs -f otel-collector`); não há backend persistente de traces nesta configuração.

**Limitações conhecidas antes da avaliação:** rate-limit e breaker são em memória por processo; workers devem iniciar um só nesta versão. Uma falha abrupta após `BRPOP` antes de gravar resultado pode perder job (sem Redis Streams/ack/reclaim); para produção, migrar para Streams ou fila com ack/parking-lot. Métricas e alertas não estão configurados.

## Segurança e LGPD

- Dados: identificador de usuário de demonstração, IP de origem mantido temporariamente no rate-limit em memória, texto enviado para inferência, resposta e identificadores/status dos jobs no Redis e payloads de texto indexados em Qdrant. Não enviar dados pessoais ou sensíveis na demonstração.
- Finalidade: autenticação, controle de abuso, execução da consulta e recuperação de contexto. Texto pode ser enviado ao provedor de IA somente quando `OPENAI_API_KEY` estiver configurada; consultar a política e região do provedor antes do uso real.
- Retenção implementada: JWT até expirar (60 min padrão); chaves de rate-limit em memória por janela de 60 s; jobs/conteúdo Redis e documentos Qdrant persistem em volumes sem TTL até exclusão manual (`docker compose down -v` apaga volumes). Planejar TTL e processo de exclusão antes de uso real; não alegar eliminação automática. Logs do app evitam registrar texto, tokens ou senha.
- Segurança: segredo JWT e senha de demonstração via `.env` local, não versionar; trocar antes de expor. Em nuvem, usar secret manager. Login de demonstração usa senha de ambiente em texto simples e não é apropriado a usuários reais; gateway deve ficar atrás do proxy HTTPS.

## HTTPS e publicação (pendente)

Compose local serve HTTP em localhost. Perfil `public` habilita Caddy, que solicita e renova certificado TLS automaticamente quando `PUBLIC_DOMAIN` aponta para um domínio DNS válido e as portas 80/443 chegam à VM:

```bash
# Configure DNS A/AAAA para VM e PUBLIC_DOMAIN=api.seudominio.example no .env
docker compose --profile public up --build -d
```

A hospedagem e o domínio devem suportar esse arranjo. Siga `deploy/GUIA.md`: selecionar explicitamente uma VM/free tier compatível com Docker Compose, configurar firewall e DNS, carregar segredos e validar `/saude` via HTTPS. Não existe URL de deploy nem cloud provisionada por este trabalho até agora.

## Trade-offs

**CAP:** no Redis da fila priorizamos consistência do estado e aceitamos indisponibilidade da submissão quando Redis não responde; não há garantia de execução durante partição. Vector store único privilegia disponibilidade eventual das leituras, sem replicação multi-região ou consistência forte entre ingestão e consulta. O Qdrant standalone é ponto único de falha; não reivindicamos tolerância a partição com consistência simultânea.

**Custo:** local Compose e modo offline não exigem custo de inferência. Qdrant/Redis/collector consomem memória; free tier depende do provedor e pode suspender/limitar VM. API externa pode cobrar por token. Usar uma única VM reduz custo e aumenta blast radius.

**Latência:** a submissão responde rapidamente (202), porém resultado inclui espera de fila, inferência, busca vetorial e possivelmente API externa. Retentativas aumentam tail latency; circuito aberto reduz cascata, retornando job failed após retries. Vetores hashing-local são intencionalmente simples, sem qualidade semântica de embedding treinado.

## Testes

```bash
python -m pip install -r requirements-dev.txt
pytest -q
python -m compileall -q services tests
# Teste integrado obrigatório em host com Docker
docker compose up --build -d
# verifique login, POST job, worker, status/result, spans e HTTPS no deploy real
```

Lista de verificação pré-entrega: `docs/ENTREGA.md`. A entrega final precisa incluir URL pública HTTPS real, teste da stack limpa em outra máquina e revisão do status de retenção/segredos.

## Referências

- Kit oficial C3.A2: https://github.com/howardroatti/sd-2026-2-kit-c3a2
- Base didática do grupo: https://github.com/bessiwolkers-droid/HOWARD_NUVEM
- C2.A2 do grupo: https://github.com/bessiwolkers-droid/C2_HOWARD_NUVEM
