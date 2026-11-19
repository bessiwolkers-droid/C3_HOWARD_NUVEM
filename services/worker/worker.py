
import os
import json
import time
import asyncio

import httpx
import redis.asyncio as redis

from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry import trace, context
from opentelemetry.propagate import extract
from opentelemetry.trace import Status, StatusCode
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.redis import RedisInstrumentor


P = TracerProvider(
    resource=Resource.create({'service.name': 'queue-worker'})
)

P.add_span_processor(
    BatchSpanProcessor(
        OTLPSpanExporter(
            endpoint=os.getenv(
                'OTEL_EXPORTER_OTLP_ENDPOINT',
                'http://otel-collector:4317'
            ),
            insecure=True
        )
    )
)

trace.set_tracer_provider(P)

T = trace.get_tracer('c3.worker')

# Instrumentação do Redis e HTTPX
RedisInstrumentor().instrument()
HTTPXClientInstrumentor().instrument()

R = redis.from_url(
    os.getenv('REDIS_URL', 'redis://redis:6379/0'),
    decode_responses=True
)

URL = os.getenv('INFERENCE_URL', 'http://inference:8001')
MAX = int(os.getenv('MAX_RETRIES', '4'))
TIMEOUT = float(os.getenv('JOB_TIMEOUT_SECONDS', '20'))


class Breaker:
    def __init__(self):
        self.failures = 0
        self.opened = 0

    async def call(self, fn):
        if self.failures >= 5:
            if time.monotonic() - self.opened < 20:
                raise RuntimeError('circuit breaker open')
            self.failures = 0

        try:
            result = await fn()
            self.failures = 0
            return result

        except Exception:
            self.failures += 1

            if self.failures >= 5:
                self.opened = time.monotonic()

            raise


B = Breaker()


async def execute(msg):
    jid = msg['job_id']

    # Recupera o contexto de rastreamento enviado pelo Gateway
    parent = extract(msg.get('trace_context', {}))
    token = context.attach(parent)

    try:
        with T.start_as_current_span('worker.process_job') as span:
            span.set_attribute('messaging.message.id', jid)
            span.set_attribute('messaging.destination.name', 'jobs')

            for attempt in range(MAX):
                try:
                    async def call():
                        async with httpx.AsyncClient(
                            timeout=httpx.Timeout(TIMEOUT, connect=3)
                        ) as c:
                            res = await c.post(
                                URL + '/infer',
                                json={
                                    'job_id': jid,
                                    'text': msg['text']
                                }
                            )

                            res.raise_for_status()
                            return res.json()

                    result = await B.call(call)

                    await R.hset(
                        f'job:{jid}',
                        mapping={
                            'status': 'completed',
                            'result': json.dumps(
                                result,
                                ensure_ascii=False
                            )
                        }
                    )

                    return

                except Exception as e:
                    if attempt + 1 == MAX:
                        span.record_exception(e)
                        span.set_status(Status(StatusCode.ERROR))

                        await R.hset(
                            f'job:{jid}',
                            mapping={
                                'status': 'failed',
                                'error': 'Inference unavailable'
                            }
                        )

                        return

                    await R.hset(
                        f'job:{jid}',
                        mapping={
                            'status': 'retrying',
                            'attempt': str(attempt + 1)
                        }
                    )

                    await asyncio.sleep(min(2 ** attempt, 8))

    finally:
        context.detach(token)


async def main():
    while True:
        item = await R.brpop('jobs', timeout=5)

        if not item:
            continue

        try:
            await execute(json.loads(item[1]))

        except Exception as e:
            print('job processing error', type(e).__name__)


if __name__ == '__main__':
    try:
        asyncio.run(main())

    except KeyboardInterrupt:
        pass
