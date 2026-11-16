# Guia de publicação HTTPS em VM de free tier

O deployment público não foi provisionado por este repositório. O provedor e plano gratuito mudam com o tempo; confirme elegibilidade, limites e disponibilidade de região diretamente antes de assumir custo. A arquitetura fornecida requer uma VM Linux com Docker Compose v2, DNS e tráfego TCP 80/443; domínios podem ter custo próprio.

1. Escolha uma VM de free tier que permita contêineres/Compose e tenha RAM suficiente (ideal 4 GB; a stack ocupa vários containers).
2. Crie DNS A para o IP público da VM; abra 80/443 no firewall do provedor. Não exponha Redis 6379, Qdrant 6333 nem OTLP externamente.
3. Clone o repositório na VM e configure `.env` com JWT_SECRET aleatório, DEMO_PASSWORD forte, PUBLIC_DOMAIN DNS e opcionalmente OPENAI_API_KEY.
4. Execute `docker compose --profile public up --build -d`; Caddy automatiza certificado ACME.
5. Verifique `https://SEU_DOMINIO/saude`, login e fluxo inteiro de job. Atualize `URL pública` no README somente com endpoint real validado.
6. Configure backup dos volumes Qdrant/Redis e revise custos/limites do provedor; nunca comite `.env`.

A VM precisa ter endereço acessível e portas encaminhadas. Não use o perfil public com `localhost` em nuvem.
