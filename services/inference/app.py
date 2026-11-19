
import os
import httpx

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor


# Configuração de observabilidade
provider = TracerProvider(
    resource=Resource.create({"service.name": "inference"})
)

provider.add_span_processor(
    BatchSpanProcessor(
        OTLPSpanExporter(
            endpoint=os.getenv(
                "OTEL_EXPORTER_OTLP_ENDPOINT",
                "http://otel-collector:4317"
            ),
            insecure=True
        )
    )
)

trace.set_tracer_provider(provider)
tracer = trace.get_tracer("c3.inference")

HTTPXClientInstrumentor().instrument()

app = FastAPI(title="Inference API")
FastAPIInstrumentor.instrument_app(app)


class Task(BaseModel):
    job_id: str
    text: str


@app.get("/saude")
def health():
    return {"status": "ok"}


@app.post("/infer")
async def infer(task: Task):

    # Busca de contexto no Vectorstore
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(4, connect=1)
        ) as client:

            response = await client.post(
                os.getenv(
                    "VECTOR_URL",
                    "http://vectorstore:8002"
                ) + "/search",
                json={
                    "text": task.text,
                    "limit": 4
                }
            )

            response.raise_for_status()
            matches = response.json()["matches"]

    except (httpx.HTTPError, KeyError) as error:
        print("ERRO VECTORSTORE:", str(error))
        raise HTTPException(
            status_code=503,
            detail="Vector service unavailable"
        ) from error

    context = "\n".join(
        item["text"] for item in matches if "text" in item
    )

    key = os.getenv("OPENAI_API_KEY", "").strip()

    # Modo offline: utiliza o contexto recuperado
    if not key:
        print("INFERENCE: executando em modo offline")

        if context:
            answer = (
                "Resposta em modo offline. "
                "Contexto encontrado na base de conhecimento:\n"
                + context
            )
        else:
            answer = (
                "Modo offline: nenhum contexto relevante foi "
                "encontrado na base de conhecimento."
            )

        return {
            "job_id": task.job_id,
            "answer": answer,
            "mode": "offline"
        }

    # Modo externo: tenta utilizar a API da OpenAI
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(12, connect=2)
        ) as client:

            response = await client.post(
                os.getenv(
                    "OPENAI_BASE_URL",
                    "https://api.openai.com/v1"
                ) + "/chat/completions",

                headers={
                    "Authorization": f"Bearer {key}"
                },

                json={
                    "model": os.getenv(
                        "OPENAI_MODEL",
                        "gpt-4o-mini"
                    ),
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "Responda em português com base "
                                "apenas no contexto. Se ele for "
                                "insuficiente, informe isso. "
                                "Contexto: " + context
                            )
                        },
                        {
                            "role": "user",
                            "content": task.text
                        }
                    ]
                }
            )

            response.raise_for_status()

            answer = response.json()["choices"][0]["message"]["content"]

            return {
                "job_id": task.job_id,
                "answer": answer,
                "mode": "external"
            }

    except (httpx.HTTPStatusError, httpx.RequestError) as error:
        print(
            "ERRO NA API EXTERNA:",
            type(error).__name__,
            str(error)
        )

        # Se a API externa falhar, utiliza o modo offline
        if context:
            answer = (
                "Resposta em modo offline devido à indisponibilidade "
                "da API externa. Contexto encontrado:\n"
                + context
            )
        else:
            answer = (
                "Modo offline: a API externa está indisponível "
                "e não foi encontrado contexto relevante."
            )

        return {
            "job_id": task.job_id,
            "answer": answer,
            "mode": "offline"
        }

    except (KeyError, ValueError) as error:
        print("ERRO NA RESPOSTA DA API:", str(error))

        raise HTTPException(
            status_code=502,
            detail="Invalid external inference response"
        ) from error
