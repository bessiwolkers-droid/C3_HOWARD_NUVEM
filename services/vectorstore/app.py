import os, hashlib, json, re, uuid
from pathlib import Path
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from qdrant_client import QdrantClient, models
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
provider=TracerProvider(resource=Resource.create({'service.name':'vectorstore'})); provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=os.getenv('OTEL_EXPORTER_OTLP_ENDPOINT','http://otel-collector:4317'),insecure=True))); trace.set_tracer_provider(provider); tracer=trace.get_tracer('c3.vectorstore'); app=FastAPI(title='Vector Store API'); FastAPIInstrumentor.instrument_app(app); client=QdrantClient(url=os.getenv('QDRANT_URL','http://qdrant:6333')); COLLECTION='howard_knowledge'; DIM=384
class Document(BaseModel): id:str|None=None; text:str=Field(min_length=1,max_length=8000)
class Search(BaseModel): text:str; limit:int=Field(default=4,ge=1,le=10)
def embed(text):
 v=[0.0]*DIM
 for word in re.findall(r'\w+',text.lower()):
  n=int(hashlib.sha256(word.encode()).hexdigest()[:8],16)%DIM; v[n]+=1.0
 norm=sum(x*x for x in v)**0.5
 return [x/norm for x in v] if norm else v
def upsert(external_id,text):
 point_id=str(uuid.uuid5(uuid.NAMESPACE_URL,external_id))
 client.upsert(collection_name=COLLECTION,points=[models.PointStruct(id=point_id,vector=embed(text),payload={'text':text,'external_id':external_id})],wait=True)
def ensure():
 if client.collection_exists(COLLECTION): return
 client.create_collection(COLLECTION,vectors_config=models.VectorParams(size=DIM,distance=models.Distance.COSINE))
 # Base inicial para a demonstracao funcionar em um clone limpo
 seed=Path(__file__).with_name('seed.json')
 if seed.is_file():
  for doc in json.loads(seed.read_text(encoding='utf-8')): upsert(doc['id'],doc['text'])
@app.get('/saude')
def health():
 try: ensure(); return {'status':'ok','collection':COLLECTION}
 except Exception as e: raise HTTPException(503,'Qdrant unavailable') from e
@app.post('/documents')
def put(d:Document):
 ensure(); external_id=d.id or hashlib.sha256(d.text.encode()).hexdigest()[:32]
 upsert(external_id,d.text)
 return {'id':external_id,'status':'stored'}
@app.post('/search')
def search(q:Search):
 ensure(); found=client.query_points(collection_name=COLLECTION,query=embed(q.text),limit=q.limit,with_payload=True).points
 return {'matches':[{'id':x.payload.get('external_id',str(x.id)),'text':x.payload.get('text',''),'score':x.score} for x in found if x.payload]}
