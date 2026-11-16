import os, httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
provider=TracerProvider(resource=Resource.create({'service.name':'inference'})); provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=os.getenv('OTEL_EXPORTER_OTLP_ENDPOINT','http://otel-collector:4317'),insecure=True))); trace.set_tracer_provider(provider); tracer=trace.get_tracer('c3.inference'); HTTPXClientInstrumentor().instrument(); app=FastAPI(title='Inference API') ; FastAPIInstrumentor.instrument_app(app)
class Task(BaseModel): job_id:str; text:str
@app.get('/saude')
def health(): return {'status':'ok'}
@app.post('/infer')
async def infer(task:Task):
 try:
  async with httpx.AsyncClient(timeout=httpx.Timeout(4,connect=1)) as c: r=await c.post(os.getenv('VECTOR_URL','http://vectorstore:8002')+'/search',json={'text':task.text,'limit':4}); r.raise_for_status(); matches=r.json()['matches']
 except (httpx.HTTPError,KeyError) as e: raise HTTPException(503,'Vector service unavailable') from e
 context='\n'.join(x['text'] for x in matches)
 key=os.getenv('OPENAI_API_KEY','')
 if key:
  try:
   async with httpx.AsyncClient(timeout=httpx.Timeout(12,connect=2)) as c:
    r=await c.post(os.getenv('OPENAI_BASE_URL','https://api.openai.com/v1')+'/chat/completions',headers={'Authorization':f'Bearer {key}'},json={'model':os.getenv('OPENAI_MODEL','gpt-4o-mini'),'messages':[{'role':'system','content':'Responda em portugues com base apenas no contexto. Se insuficiente, diga isso. Contexto: '+context},{'role':'user','content':task.text}]}); r.raise_for_status(); answer=r.json()['choices'][0]['message']['content']
  except httpx.HTTPError as e: raise HTTPException(502,'External inference API failed') from e
 else: answer=('Resposta demonstrativa offline baseada nos documentos: '+context[:1000]) if context else 'Modo offline: nenhum contexto relevante foi encontrado; configure OPENAI_API_KEY para inferencia externa.'
 return {'job_id':task.job_id,'answer':answer,'sources':[m['id'] for m in matches],'mode':'external' if key else 'offline'}
