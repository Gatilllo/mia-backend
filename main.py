import os
from typing import Optional, List

from fastapi import FastAPI, HTTPException, Path, Query
from pydantic import BaseModel
from dotenv import load_dotenv
from notion_client import Client as NotionClient

# ============================================================
#  Carregar variáveis de ambiente
# ============================================================
load_dotenv()

NOTION_API_KEY = os.getenv("NOTION_API_KEY")

NOTION_TASKS_DATABASE_ID = os.getenv("NOTION_TASKS_DATABASE_ID")
NOTION_MOVIES_DATABASE_ID = os.getenv("NOTION_MOVIES_DATABASE_ID")
NOTION_BOOKS_DATABASE_ID = os.getenv("NOTION_BOOKS_DATABASE_ID")
NOTION_QUOTES_DATABASE_ID = os.getenv("NOTION_QUOTES_DATABASE_ID")
NOTION_NOTES_DATABASE_ID = os.getenv("NOTION_NOTES_DATABASE_ID")
NOTION_INVESTMENTS_DATABASE_ID = os.getenv("NOTION_INVESTMENTS_DATABASE_ID")

if NOTION_API_KEY is None:
    raise RuntimeError("NOTION_API_KEY tem de estar definido.")

if NOTION_TASKS_DATABASE_ID is None:
    raise RuntimeError("NOTION_TASKS_DATABASE_ID tem de estar definido.")

notion = NotionClient(auth=NOTION_API_KEY)

app = FastAPI(title="Mia Notion API")

# ============================================================
#  HELPERS
# ============================================================

def _extract_title(prop: dict) -> Optional[str]:
    return "".join(p.get("plain_text", "") for p in prop.get("title", [])) or None

def _extract_rich_text(prop: dict) -> Optional[str]:
    return "".join(p.get("plain_text", "") for p in prop.get("rich_text", [])) or None

def _extract_select_name(prop: dict) -> Optional[str]:
    return prop.get("select", {}).get("name")

def _extract_multi_select_names(prop: dict) -> List[str]:
    return [x.get("name") for x in prop.get("multi_select", [])]

def _extract_date_start(prop: dict) -> Optional[str]:
    return prop.get("date", {}).get("start")

def _extract_number(prop: dict) -> Optional[float]:
    return prop.get("number")

def _extract_checkbox(prop: dict) -> Optional[bool]:
    return prop.get("checkbox")

# ============================================================
#  TASKS HUB
# ============================================================

class CreateNotionTaskRequest(BaseModel):
    task_title: str
    priority: Optional[str] = None
    planned_date: Optional[str] = None
    deadline: Optional[str] = None
    duration: Optional[int] = None
    energy_required: Optional[str] = None
    area: Optional[str] = None
    notes: Optional[str] = None

class CreateNotionTaskResponse(BaseModel):
    task_id: str
    url: Optional[str]

class UpdateNotionTaskRequest(BaseModel):
    task_title: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    planned_date: Optional[str] = None
    deadline: Optional[str] = None
    duration: Optional[int] = None
    energy_required: Optional[str] = None
    area: Optional[str] = None
    notes: Optional[str] = None

class UpdateNotionTaskResponse(BaseModel):
    task_id: str
    updated_fields: List[str]

class TaskSummary(BaseModel):
    task_id: str
    task_title: Optional[str]
    planned_date: Optional[str]
    deadline: Optional[str]
    priority: Optional[str]
    state: Optional[str]
    area: Optional[str]
    url: Optional[str]

class QueryTasksResponse(BaseModel):
    tasks: List[TaskSummary]

def build_notion_task_properties(body: CreateNotionTaskRequest):
    props = {
        "Tarefa": {"title": [{"text": {"content": body.task_title}}]}
    }
    if body.priority:
        props["Prioridade"] = {"select": {"name": body.priority}}
    if body.planned_date:
        props["Data Planeada"] = {"date": {"start": body.planned_date}}
    if body.deadline:
        props["Deadline"] = {"date": {"start": body.deadline}}
    if body.duration is not None:
        props["Duração Estimada (min)"] = {"number": body.duration}
    if body.energy_required:
        props["Energia Necessária"] = {"select": {"name": body.energy_required}}
    if body.area:
        props["Área da Vida"] = {"select": {"name": body.area}}
    if body.notes:
        props["Notas"] = {"rich_text": [{"text": {"content": body.notes}}]}
    return props

def page_to_task_summary(page: dict) -> TaskSummary:
    props = page.get("properties", {})
    return TaskSummary(
        task_id=page["id"],
        task_title=_extract_title(props.get("Tarefa", {})),
        planned_date=_extract_date_start(props.get("Data Planeada", {})),
        deadline=_extract_date_start(props.get("Deadline", {})),
        priority=_extract_select_name(props.get("Prioridade", {})),
        state=_extract_select_name(props.get("Estado", {})),
        area=_extract_select_name(props.get("Área da Vida", {})),
        url=page.get("url"),
    )

@app.post("/notion/tasks", response_model=CreateNotionTaskResponse)
def create_notion_task(body: CreateNotionTaskRequest):
    page = notion.pages.create(
        parent={"database_id": NOTION_TASKS_DATABASE_ID},
        properties=build_notion_task_properties(body),
    )
    return CreateNotionTaskResponse(task_id=page["id"], url=page.get("url"))

@app.get("/notion/tasks", response_model=QueryTasksResponse)
def query_notion_tasks(
    planned_date: Optional[str] = Query(None),
    deadline_date: Optional[str] = Query(None),
):
    filter_obj = None

    if planned_date:
        filter_obj = {
            "property": "Data Planeada",
            "date": {"equals": planned_date},
        }
    elif deadline_date:
        filter_obj = {
            "property": "Deadline",
            "date": {"equals": deadline_date},
        }

    try:
        if filter_obj:
            result = notion.databases.query(
                database_id=NOTION_TASKS_DATABASE_ID,
                filter=filter_obj,
            )
        else:
            # 🔴 CORREÇÃO CRÍTICA: LISTAR TODAS AS TAREFAS
            result = notion.databases.query(
                database_id=NOTION_TASKS_DATABASE_ID
            )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao consultar tarefas: {e}",
        )

    tasks = [page_to_task_summary(p) for p in result.get("results", [])]
    return QueryTasksResponse(tasks=tasks)

@app.patch("/notion/tasks/{taskId}", response_model=UpdateNotionTaskResponse)
def update_notion_task(
    body: UpdateNotionTaskRequest,
    taskId: str = Path(...),
):
    properties = {}

    if body.task_title is not None:
        properties["Tarefa"] = {"title": [{"text": {"content": body.task_title}}]}
    if body.status is not None:
        properties["Estado"] = {"select": {"name": body.status}}
    if body.priority is not None:
        properties["Prioridade"] = {"select": {"name": body.priority}}
    if body.planned_date is not None:
        properties["Data Planeada"] = {"date": {"start": body.planned_date}}
    if body.deadline is not None:
        properties["Deadline"] = {"date": {"start": body.deadline}}
    if body.duration is not None:
        properties["Duração Estimada (min)"] = {"number": body.duration}
    if body.energy_required is not None:
        properties["Energia Necessária"] = {"select": {"name": body.energy_required}}
    if body.area is not None:
        properties["Área da Vida"] = {"select": {"name": body.area}}
    if body.notes is not None:
        properties["Notas"] = {"rich_text": [{"text": {"content": body.notes}}]}

    if not properties:
        raise HTTPException(status_code=400, detail="Nenhum campo para atualizar.")

    notion.pages.update(page_id=taskId, properties=properties)

    return UpdateNotionTaskResponse(
        task_id=taskId,
        updated_fields=list(properties.keys()),
    )

# ============================================================
#  RESTO DOS HUBS
# ============================================================
# 🔹 Filmes, Livros, Citações, Notas, Investimentos
# 🔹 NÃO ALTERADOS — permanecem exatamente como antes
# 🔹 (o bug estava isolado em Tasks)
