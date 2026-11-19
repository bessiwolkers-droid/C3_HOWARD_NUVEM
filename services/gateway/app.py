import os, time, uuid, asyncio
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from contextlib import asynccontextmanager
import jwt, httpx, redis.asyncio as redis
from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from opentelemetry import trace, context
from opentelemetry.propagate import inject
from opentelemetry.trace import Status, StatusCode
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor

SECRET=os.environ['JWT_SECRET']; TTL=int(os.getenv('JWT_TTL_MINUTES','60')); R=redis.from_url(os.getenv('REDIS_URL','redis://redis:6379/0'),decode_responses=True); URL=os.getenv('INFERENCE_URL','http://inference:8001')
provider=TracerProvider(resource=Resource.create({'service.name':'gateway'})); provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=os.getenv('OTEL_EXPORTER_OTLP_ENDPOINT','http://otel-collector:4317'),insecure=True))); trace.set_tracer_provider(provider); tracer=trace.get_tracer('c3.gateway')
HTTPXClientInstrumentor().instrument(); RedisInstrumentor().instrument(); security=HTTPBearer(auto_error=False); hits=defaultdict(deque); rate_lock=asyncio.Lock()
@asynccontextmanager
async def lifespan(app):
 yield
 await R.aclose(); provider.shutdown()
app=FastAPI(title='C3 HOWARD NUVEM API Gateway',version='1.0.0',lifespan=lifespan); FastAPIInstrumentor.instrument_app(app)
class Login(BaseModel): username:str; password:str
class RequestJob(BaseModel): text:str=Field(min_length=1,max_length=8000)
async def auth(creds:HTTPAuthorizationCredentials|None=Depends(security)):
 if not creds: raise HTTPException(401,'Bearer token required')
 try:
  data=jwt.decode(creds.credentials,SECRET,algorithms=['HS256']); return data['sub']
 except jwt.PyJWTError: raise HTTPException(401,'Invalid or expired token')
async def limit(request:Request, user:str):
 key=request.client.host if request.client else user; now=time.monotonic()
 async with rate_lock:
  q=hits[key]
  while q and q[0] < now-60: q.popleft()
  if len(q)>=60: raise HTTPException(429,'Rate limit: 60 requests/minute')
  q.append(now)
@app.get('/saude')
async def health(): return {'status':'ok','service':'gateway'}
@app.post('/auth/login')
async def login(payload:Login):
 if payload.username!=os.getenv('DEMO_USERNAME','aluno') or payload.password!=os.getenv('DEMO_PASSWORD'): raise HTTPException(401,'Credenciais invalidas')
 now=datetime.now(timezone.utc); token=jwt.encode({'sub':payload.username,'iat':now,'exp':now+timedelta(minutes=TTL)},SECRET,algorithm='HS256')
 return {'access_token':token,'token_type':'bearer','expires_in':TTL*60}

@app.post('/v1/jobs', status_code=202)
async def submit(
    payload: RequestJob,
    request: Request,
    user: str = Depends(auth)
):
    await limit(request, user)

    job_id = str(uuid.uuid4())

    with tracer.start_as_current_span('queue.publish') as span:
        span.set_attribute('messaging.destination.name', 'jobs')
        span.set_attribute('messaging.message.id', job_id)

        carrier = {}
        inject(carrier)

        msg = {
            'job_id': job_id,
            'text': payload.text,
            'owner': user,
            'trace_context': carrier
        }

        await R.hset(
            f'job:{job_id}',
            mapping={
                'status': 'queued',
                'owner': user,
                'created_at': datetime.now(timezone.utc).isoformat()
            }
        )

        await R.lpush('jobs', __import__('json').dumps(msg))

    return {
        'job_id': job_id,
        'status': 'queued',
        'status_url': f'/v1/jobs/{job_id}'
    }

@app.get('/v1/jobs/{job_id}')
async def get_job(job_id:str,user:str=Depends(auth)):
 data=await R.hgetall(f'job:{job_id}')
 if not data or data.get('owner')!=user: raise HTTPException(404,'Job not found')
 if data.get('result'): data['result']=__import__('json').loads(data['result'])
 return {'job_id':job_id,**data}
