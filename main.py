import os
from typing import Optional, List
from datetime import date as date_cls, datetime

from fastapi import FastAPI, HTTPException, Path, Query
from pydantic import BaseModel
from dotenv import load_dotenv
from notion_client import Client as NotionClient

# ============================================================
# Configuração inicial
# ============================================================

load_dotenv()

NOTION_API_KEY = os.getenv("NOTION_API_KEY")
NOTION_TASKS_DATABASE_ID = os.getenv("NOTION_TASKS_DATABASE_ID")

if NOTION_API_KEY is None or NOTION_TASKS_DATABASE_ID is None:
    raise RuntimeError(
        "NOTION_API_KEY e NOTION_TASKS_DATABASE_ID têm de estar definidos nas variáveis de ambiente."
    )

notion = NotionClient(auth=NOTION_API_KEY)

app = FastAPI(title="Mia Notion API")


# ============================================================
# Modelos Pydantic
# ============================================================

class CreateNotionTaskRequest(BaseModel):
    task_title: str
    priority: Optional[str] = None
    planned_date: Optional[str] = None  # YYYY-MM-DD
    deadline: Optional[str] = None      # YYYY-MM-DD
    duration: Optional[int] = None      # minutos
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
    priority: Optional[str]
    state: Optional[str]
    planned_date: Optional[str]
    deadline: Optional[str]
    area_of_life: Optional[str]
    energy_level: Optional[str]
    duration_minutes: Optional[int]
    url: Optional[str]


class QueryTasksResponse(BaseModel):
    tasks: List[TaskSummary]


# ============================================================
# Helpers para mapear propriedades do Notion
# ============================================================

def build_notion_task_properties(body: CreateNotionTaskRequest):
    """
    Constrói o dicionário de propriedades para criar uma página no Notion.
    Os nomes das propriedades têm de bater certo com a base Task Hub 2.0.
    """
    props = {
        "Tarefa": {
            "title": [{"text": {"content": body.task_title}}],
        }
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


def _extract_title(prop: dict) -> Optional[str]:
    title = prop.get("title")
    if not title:
        return None
    return "".join([t.get("plain_text", "") for t in title])


def _extract_select(prop: dict) -> Optional[str]:
    select = prop.get("select")
    if not select:
        return None
    return select.get("name")


def _extract_number(prop: dict) -> Optional[int]:
    return prop.get("number")


def _extract_date(prop: dict) -> Optional[str]:
    date_val = prop.get("date")
    if not date_val:
        return None
    return date_val.get("start")


def _page_to_task(page: dict) -> TaskSummary:
    """
    Converte um registo (page) do Notion num resumo de tarefa.
    """
    props = page.get("properties", {})

    return TaskSummary(
        task_id=page.get("id"),
        task_title=_extract_title(props.get("Tarefa", {})),
        priority=_extract_select(props.get("Prioridade", {})),
        state=_extract_select(props.get("Estado", {})),
        planned_date=_extract_date(props.get("Data Planeada", {})),
        deadline=_extract_date(props.get("Deadline", {})),
        area_of_life=_extract_select(props.get("Área da Vida", {})),
        energy_level=_extract_select(props.get("Energia Necessária", {})),
        duration_minutes=_extract_number(props.get("Duração Estimada (min)", {})),
        url=page.get("url"),
    )


# ============================================================
# Endpoints: criar / actualizar tarefa
# ============================================================

@app.post("/notion/tasks", response_model=CreateNotionTaskResponse)
def create_notion_task(body: CreateNotionTaskRequest):
    """
    Cria uma nova tarefa na base Task Hub 2.0.
    """
    try:
        props = build_notion_task_properties(body)
        page = notion.pages.create(
            parent={"database_id": NOTION_TASKS_DATABASE_ID},
            properties=props,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Erro ao criar tarefa no Notion: {e}")

    return CreateNotionTaskResponse(
        task_id=page["id"],
        url=page.get("url"),
    )


@app.patch("/notion/tasks/{taskId}", response_model=UpdateNotionTaskResponse)
def update_notion_task(
    body: UpdateNotionTaskRequest,
    taskId: str = Path(..., description="ID da tarefa no Notion"),
):
    """
    Actualiza campos de uma tarefa existente na base Task Hub 2.0.
    Só altera os campos presentes no corpo do pedido.
    """
    properties: dict = {}

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
        raise HTTPException(status_code=400, detail="Nenhum campo para actualizar.")

    try:
        notion.pages.update(page_id=taskId, properties=properties)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Erro ao actualizar tarefa no Notion: {e}")

    updated_fields = list(properties.keys())

    return UpdateNotionTaskResponse(task_id=taskId, updated_fields=updated_fields)


# ============================================================
# Endpoint: consultar tarefas por dia
# ============================================================

@app.get("/notion/tasks", response_model=QueryTasksResponse)
def get_tasks_for_date(
    target_date: Optional[date_cls] = Query(
        None,
        description="Data alvo no formato YYYY-MM-DD. Se não for enviada, assume hoje.",
    ),
):
    """
    Devolve as tarefas cuja Data Planeada OU Deadline coincidam com a data indicada.
    Se `target_date` não vier, usa a data de hoje.
    """
    # Se não vier target_date, usar hoje
    if target_date is None:
        target_date = datetime.today().date()

    iso_date = target_date.isoformat()

    try:
        response = notion.databases.query(
            database_id=NOTION_TASKS_DATABASE_ID,
            filter={
                "or": [
                    {"property": "Data Planeada", "date": {"equals": iso_date}},
                    {"property": "Deadline", "date": {"equals": iso_date}},
                ]
            },
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao consultar tarefas: {e}")

    pages = response.get("results", [])
    tasks = [_page_to_task(page) for page in pages]

    return QueryTasksResponse(tasks=tasks)
