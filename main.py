import os
from typing import Optional, List
from datetime import date as date_cls


from fastapi import FastAPI, HTTPException, Path
from pydantic import BaseModel
from dotenv import load_dotenv
from notion_client import Client as NotionClient

# Carregar variáveis de ambiente
load_dotenv()

NOTION_API_KEY = os.getenv("NOTION_API_KEY")
NOTION_TASKS_DATABASE_ID = os.getenv("NOTION_TASKS_DATABASE_ID")

if NOTION_API_KEY is None or NOTION_TASKS_DATABASE_ID is None:
    raise RuntimeError("NOTION_API_KEY e NOTION_TASKS_DATABASE_ID têm de estar definidos nas variáveis de ambiente.")

notion = NotionClient(auth=NOTION_API_KEY)

app = FastAPI(title="Mia Notion API")

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


def build_notion_task_properties(body: CreateNotionTaskRequest):
    # ATENÇÃO: estes nomes têm de bater certo com os nomes das tuas colunas no Notion
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


@app.post("/notion/tasks", response_model=CreateNotionTaskResponse)
def create_notion_task(body: CreateNotionTaskRequest):
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
        raise HTTPException(status_code=400, detail="Nenhum campo para actualizar.")

    try:
        notion.pages.update(page_id=taskId, properties=properties)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Erro ao actualizar tarefa no Notion: {e}")

    updated_fields = list(properties.keys())

    return UpdateNotionTaskResponse(task_id=taskId, updated_fields=updated_fields)

from fastapi import Query

def _extract_title(prop):
    title = prop.get("title")
    if not title:
        return None
    return "".join([t.get("plain_text", "") for t in title])

def _extract_select(prop):
    select = prop.get("select")
    if not select:
        return None
    return select.get("name")

def _extract_number(prop):
    return prop.get("number")

def _extract_date(prop):
    date_val = prop.get("date")
    if not date_val:
        return None
    return date_val.get("start")

def _page_to_task(page: dict) -> dict:
    props = page.get("properties", {})
    return {
        "task_id": page.get("id"),
        "task_title": _extract_title(props.get("Tarefa", {})),
        "priority": _extract_select(props.get("Prioridade", {})),
        "state": _extract_select(props.get("Estado", {})),
        "planned_date": _extract_date(props.get("Data Planeada", {})),
        "deadline": _extract_date(props.get("Deadline", {})),
        "area_of_life": _extract_select(props.get("Área da Vida", {})),
        "energy_level": _extract_select(props.get("Energia Necessária", {})),
        "duration_minutes": _extract_number(props.get("Duração Estimada (min)", {})),
        "url": page.get("url"),
    }

@app.get("/notion/tasks")
async def query_tasks(
    date: Optional[str] = Query(None, description="YYYY-MM-DD"),
    from_: Optional[str] = Query(None, alias="from", description="YYYY-MM-DD"),
    to: Optional[str] = Query(None, description="YYYY-MM-DD"),
    scope: str = Query("both", description="planned | deadline | both"),
    overdue: bool = False,
):
    """
    Consulta tarefas na base Task Hub 2.0.

    - Se `overdue` = true  -> tarefas atrasadas (Deadline < hoje, Estado != Concluído/Cancelado)
    - Se `date` definido    -> tarefas desse dia (Data Planeada e/ou Deadline, consoante `scope`)
    - Se `from`/`to`        -> intervalo de datas (Data Planeada e/ou Deadline)
    """

    try:
        filter_obj = None

        # 1) Tarefas atrasadas
        if overdue:
            today_str = date_cls.today().isoformat()
            filter_obj = {
                "and": [
                    {
                        "property": "Deadline",
                        "date": {"before": today_str},
                    },
                    {
                        "property": "Estado",
                        "select": {"does_not_equal": "Concluído"},
                    },
                    {
                        "property": "Estado",
                        "select": {"does_not_equal": "Cancelado"},
                    },
                ]
            }

        # 2) Tarefas de um dia específico (ex.: hoje, amanhã)
        elif date:
            per_props = []
            if scope in ("planned", "both"):
                per_props.append(
                    {
                        "property": "Data Planeada",
                        "date": {"equals": date},
                    }
                )
            if scope in ("deadline", "both"):
                per_props.append(
                    {
                        "property": "Deadline",
                        "date": {"equals": date},
                    }
                )

            if len(per_props) == 1:
                filter_obj = per_props[0]
            elif len(per_props) > 1:
                filter_obj = {"or": per_props}

        # 3) Intervalo de datas (ex.: esta semana)
        elif from_ or to:
            range_filters = []
            if scope in ("planned", "both"):
                cond = {"property": "Data Planeada", "date": {}}
                if from_:
                    cond["date"]["on_or_after"] = from_
                if to:
                    cond["date"]["on_or_before"] = to
                range_filters.append(cond)
            if scope in ("deadline", "both"):
                cond = {"property": "Deadline", "date": {}}
                if from_:
                    cond["date"]["on_or_after"] = from_
                if to:
                    cond["date"]["on_or_before"] = to
                range_filters.append(cond)

            if len(range_filters) == 1:
                filter_obj = range_filters[0]
            elif len(range_filters) > 1:
                filter_obj = {"or": range_filters}

        # 4) Se não houver nenhum filtro explícito, devolve tarefas ativas (não concluídas/canceladas)
        if filter_obj is None:
            filter_obj = {
                "and": [
                    {
                        "property": "Estado",
                        "select": {"does_not_equal": "Concluído"},
                    },
                    {
                        "property": "Estado",
                        "select": {"does_not_equal": "Cancelado"},
                    },
                ]
            }

        # Chamada ao Notion
        result = notion.databases.query(
            database_id=NOTION_TASKS_DATABASE_ID,
            filter=filter_obj,
        )

        tasks = [_page_to_task(page) for page in result.get("results", [])]

        return {"tasks": tasks}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao consultar tarefas: {e}")
