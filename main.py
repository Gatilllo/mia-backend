import os
from typing import Optional, List

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
