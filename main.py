import os
from typing import Optional, List

from fastapi import FastAPI, HTTPException, Path, Query
from pydantic import BaseModel
from dotenv import load_dotenv
from notion_client import Client as NotionClient

# ============================================================
#  ENV
# ============================================================
load_dotenv()

NOTION_API_KEY = os.getenv("NOTION_API_KEY")
NOTION_TASKS_DATABASE_ID = os.getenv("NOTION_TASKS_DATABASE_ID")
NOTION_MOVIES_DATABASE_ID = os.getenv("NOTION_MOVIES_DATABASE_ID")
NOTION_BOOKS_DATABASE_ID = os.getenv("NOTION_BOOKS_DATABASE_ID")
NOTION_QUOTES_DATABASE_ID = os.getenv("NOTION_QUOTES_DATABASE_ID")
NOTION_NOTES_DATABASE_ID = os.getenv("NOTION_NOTES_DATABASE_ID")
NOTION_INVESTMENTS_DATABASE_ID = os.getenv("NOTION_INVESTMENTS_DATABASE_ID")

if not NOTION_API_KEY:
    raise RuntimeError("NOTION_API_KEY não definido")

if not NOTION_TASKS_DATABASE_ID:
    raise RuntimeError("NOTION_TASKS_DATABASE_ID não definido")

notion = NotionClient(auth=NOTION_API_KEY)
app = FastAPI(title="Mia Notion API")

# ============================================================
#  HELPERS
# ============================================================
def _title(prop): return "".join(p.get("plain_text","") for p in prop.get("title",[])) or None
def _rich(prop): return "".join(p.get("plain_text","") for p in prop.get("rich_text",[])) or None
def _select(prop): return prop.get("select",{}).get("name")
def _multi(prop): return [x.get("name") for x in prop.get("multi_select",[])]
def _date(prop): return prop.get("date",{}).get("start")
def _num(prop): return prop.get("number")
def _check(prop): return prop.get("checkbox")

# ============================================================
#  TASKS HUB
# ============================================================
class CreateTask(BaseModel):
    task_title: str
    priority: Optional[str]=None
    planned_date: Optional[str]=None
    deadline: Optional[str]=None
    duration: Optional[int]=None
    energy_required: Optional[str]=None
    area: Optional[str]=None
    notes: Optional[str]=None

class TaskSummary(BaseModel):
    task_id: str
    task_title: Optional[str]
    planned_date: Optional[str]
    deadline: Optional[str]
    priority: Optional[str]
    state: Optional[str]
    area: Optional[str]
    url: Optional[str]

class TasksResponse(BaseModel):
    tasks: List[TaskSummary]

def _task_props(b: CreateTask):
    p={"Tarefa":{"title":[{"text":{"content":b.task_title}}]}}
    if b.priority: p["Prioridade"]={"select":{"name":b.priority}}
    if b.planned_date: p["Data Planeada"]={"date":{"start":b.planned_date}}
    if b.deadline: p["Deadline"]={"date":{"start":b.deadline}}
    if b.duration is not None: p["Duração Estimada (min)"]={"number":b.duration}
    if b.energy_required: p["Energia Necessária"]={"select":{"name":b.energy_required}}
    if b.area: p["Área da Vida"]={"select":{"name":b.area}}
    if b.notes: p["Notas"]={"rich_text":[{"text":{"content":b.notes}}]}
    return p

def _task_summary(pg):
    pr=pg["properties"]
    return TaskSummary(
        task_id=pg["id"],
        task_title=_title(pr.get("Tarefa",{})),
        planned_date=_date(pr.get("Data Planeada",{})),
        deadline=_date(pr.get("Deadline",{})),
        priority=_select(pr.get("Prioridade",{})),
        state=_select(pr.get("Estado",{})),
        area=_select(pr.get("Área da Vida",{})),
        url=pg.get("url"),
    )

@app.post("/notion/tasks")
def create_task(body: CreateTask):
    pg=notion.pages.create(parent={"database_id":NOTION_TASKS_DATABASE_ID},properties=_task_props(body))
    return {"task_id":pg["id"],"url":pg.get("url")}

@app.get("/notion/tasks", response_model=TasksResponse)
def list_tasks(planned_date: Optional[str]=None, deadline_date: Optional[str]=None):
    flt=None
    if planned_date:
        flt={"property":"Data Planeada","date":{"equals":planned_date}}
    elif deadline_date:
        flt={"property":"Deadline","date":{"equals":deadline_date}}

    res=notion.databases.query(database_id=NOTION_TASKS_DATABASE_ID, filter=flt) if flt \
        else notion.databases.query(database_id=NOTION_TASKS_DATABASE_ID)

    return TasksResponse(tasks=[_task_summary(p) for p in res["results"]])

# ============================================================
#  MOVIES HUB
# ============================================================
class MovieIn(BaseModel):
    title: str
    watched: Optional[bool]=False
    categories: Optional[List[str]]=None
    notes: Optional[str]=None

@app.post("/notion/movies")
def create_movie(b: MovieIn):
    p={"Filme":{"title":[{"text":{"content":b.title}}]}}
    if b.categories: p["Categoria"]={"multi_select":[{"name":c} for c in b.categories]}
    if b.watched is not None: p["Já Vi"]={"checkbox":b.watched}
    if b.notes: p["Notas"]={"rich_text":[{"text":{"content":b.notes}}]}
    return notion.pages.create(parent={"database_id":NOTION_MOVIES_DATABASE_ID},properties=p)

# ============================================================
#  BOOKS HUB
# ============================================================
class BookIn(BaseModel):
    title: str
    author: Optional[str]=None
    status: Optional[str]=None
    favorite: Optional[bool]=None
    notes: Optional[str]=None

@app.post("/notion/books")
def create_book(b: BookIn):
    p={"Título":{"title":[{"text":{"content":b.title}}]}}
    if b.author: p["Autor"]={"rich_text":[{"text":{"content":b.author}}]}
    if b.status: p["Estado de leitura"]={"select":{"name":b.status}}
    if b.favorite is not None: p["Favorito"]={"checkbox":b.favorite}
    if b.notes: p["Notas"]={"rich_text":[{"text":{"content":b.notes}}]}
    return notion.pages.create(parent={"database_id":NOTION_BOOKS_DATABASE_ID},properties=p)

# ============================================================
#  QUOTES HUB
# ============================================================
class QuoteIn(BaseModel):
    text: str
    author: Optional[str]=None
    source: Optional[str]=None
    category: Optional[str]=None
    favorite: Optional[bool]=None
    notes: Optional[str]=None

@app.post("/notion/quotes")
def create_quote(b: QuoteIn):
    p={"Texto":{"title":[{"text":{"content":b.text}}]}}
    if b.author: p["Autor"]={"rich_text":[{"text":{"content":b.author}}]}
    if b.source: p["Fonte"]={"rich_text":[{"text":{"content":b.source}}]}
    if b.category: p["Categoria"]={"select":{"name":b.category}}
    if b.favorite is not None: p["Favorita"]={"checkbox":b.favorite}
    if b.notes: p["Notas"]={"rich_text":[{"text":{"content":b.notes}}]}
    return notion.pages.create(parent={"database_id":NOTION_QUOTES_DATABASE_ID},properties=p)

# ============================================================
#  NOTES HUB
# ============================================================
class NoteIn(BaseModel):
    title: str
    category: Optional[str]=None
    emotional_energy: Optional[str]=None
    impact: Optional[str]=None
    favorite: Optional[bool]=None
    date: Optional[str]=None
    details: Optional[str]=None

@app.post("/notion/notes")
def create_note(b: NoteIn):
    p={"Título / Nota":{"title":[{"text":{"content":b.title}}]}}
    if b.category: p["Categoria"]={"select":{"name":b.category}}
    if b.emotional_energy: p["Energia emocional"]={"select":{"name":b.emotional_energy}}
    if b.impact: p["Impacto"]={"select":{"name":b.impact}}
    if b.favorite is not None: p["Favorito"]={"checkbox":b.favorite}
    if b.date: p["Data"]={"date":{"start":b.date}}
    if b.details: p["Notas detalhadas"]={"rich_text":[{"text":{"content":b.details}}]}
    return notion.pages.create(parent={"database_id":NOTION_NOTES_DATABASE_ID},properties=p)

# ============================================================
#  INVESTMENTS HUB
# ============================================================
class InvestmentIn(BaseModel):
    ativo: str
    quantidade: float
    average_price_usd: float
    aporte_total_usd: float
    saldo_atual_usd: float
    lucro_usd: float
    percent_lucro: float
    tipo_ativo: Optional[str]=None

class BulkInv(BaseModel):
    investments: List[InvestmentIn]

@app.post("/notion/investments/bulk")
def bulk_investments(b: BulkInv):
    created=[]
    for i in b.investments:
        p={
            "Ativo":{"title":[{"text":{"content":i.ativo}}]},
            "Quantidade":{"number":i.quantidade},
            "Preço Médio (USD)":{"number":i.average_price_usd},
            "Aportes Totais (USD)":{"number":i.aporte_total_usd},
            "Saldo Atual (USD)":{"number":i.saldo_atual_usd},
            "Lucro (USD)":{"number":i.lucro_usd},
            "% Lucro":{"number":i.percent_lucro},
            "Último Preço Capturado (USD)":{"number":0.0},
        }
        if i.tipo_ativo:
            p["Tipo de Ativo"]={"select":{"name":i.tipo_ativo}}
        created.append(notion.pages.create(parent={"database_id":NOTION_INVESTMENTS_DATABASE_ID},properties=p))
    return created
