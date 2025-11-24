import os
from typing import Optional, List

from fastapi import FastAPI, HTTPException, Path, Query
from pydantic import BaseModel
from dotenv import load_dotenv
from notion_client import Client as NotionClient

# ============================================================
#  Variáveis de ambiente / Notion
# ============================================================
load_dotenv()

NOTION_API_KEY = os.getenv("NOTION_API_KEY")
NOTION_TASKS_DATABASE_ID = os.getenv("NOTION_TASKS_DATABASE_ID")
NOTION_MOVIES_DATABASE_ID = os.getenv("NOTION_MOVIES_DATABASE_ID")

if NOTION_API_KEY is None:
    raise RuntimeError("NOTION_API_KEY tem de estar definido nas variáveis de ambiente.")

if NOTION_TASKS_DATABASE_ID is None:
    raise RuntimeError("NOTION_TASKS_DATABASE_ID tem de estar definido nas variáveis de ambiente.")

# NOTION_MOVIES_DATABASE_ID é opcional (depende se configuraste Filmes Hub ou não)

notion = NotionClient(auth=NOTION_API_KEY)

app = FastAPI(title="Mia Notion API")

# Constantes para nomes de propriedades no Notion
TASK_TITLE_PROP = "Tarefa"
TASK_PRIORITY_PROP = "Prioridade"
TASK_PLANNED_DATE_PROP = "Data Planeada"
TASK_DEADLINE_PROP = "Deadline"
TASK_DURATION_PROP = "Duração Estimada (min)"
TASK_ENERGY_PROP = "Energia Necessária"
TASK_AREA_PROP = "Área da Vida"
TASK_STATE_PROP = "Estado"
TASK_NOTES_PROP = "Notas"

MOVIE_TITLE_PROP = "Filme"
MOVIE_WATCHED_PROP = "Já Vi"
MOVIE_NOTES_PROP = "Notas"


# ============================================================
#  MODELOS – TASK HUB (tarefas)
# ============================================================

class CreateNotionTaskRequest(BaseModel):
    task_title: str
    priority: Optional[str] = None            # Alta | Média | Baixa
    planned_date: Optional[str] = None        # YYYY-MM-DD
    deadline: Optional[str] = None            # YYYY-MM-DD
    duration: Optional[int] = None            # minutos
    energy_required: Optional[str] = None     # Alta | Média | Baixa
    area: Optional[str] = None                # Trabalho | Saúde | Pessoal | Família | Aprendizagem ...
    notes: Optional[str] = None


class CreateNotionTaskResponse(BaseModel):
    task_id: str
    url: Optional[str]


class UpdateNotionTaskRequest(BaseModel):
    task_title: Optional[str] = None
    status: Optional[str] = None              # Inbox, Essencial, Leve, Delegável, Adiável, Concluída, ...
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
    task_title: Optional[str] = None
    planned_date: Optional[str] = None
    deadline: Optional[str] = None
    priority: Optional[str] = None
    state: Optional[str] = None
    area: Optional[str] = None
    url: Optional[str] = None


class QueryTasksResponse(BaseModel):
    tasks: List[TaskSummary]


# ============================================================
#  HELPERS – TASK HUB
# ============================================================

def build_notion_task_properties(body: CreateNotionTaskRequest):
    props = {
        TASK_TITLE_PROP: {
            "title": [{"text": {"content": body.task_title}}],
        }
    }

    if body.priority:
        props[TASK_PRIORITY_PROP] = {"select": {"name": body.priority}}

    if body.planned_date:
        props[TASK_PLANNED_DATE_PROP] = {"date": {"start": body.planned_date}}

    if body.deadline:
        props[TASK_DEADLINE_PROP] = {"date": {"start": body.deadline}}

    if body.duration is not None:
        props[TASK_DURATION_PROP] = {"number": body.duration}

    if body.energy_required:
        props[TASK_ENERGY_PROP] = {"select": {"name": body.energy_required}}

    if body.area:
        props[TASK_AREA_PROP] = {"select": {"name": body.area}}

    if body.notes:
        props[TASK_NOTES_PROP] = {"rich_text": [{"text": {"content": body.notes}}]}

    return props


def _extract_title(prop: dict) -> Optional[str]:
    title = prop.get("title")
    if not title:
        return None
    return "".join(part.get("plain_text", "") for part in title)


def _extract_select_name(prop: dict) -> Optional[str]:
    sel = prop.get("select")
    if not sel:
        return None
    return sel.get("name")


def _extract_date_start(prop: dict) -> Optional[str]:
    date_val = prop.get("date")
    if not date_val:
        return None
    return date_val.get("start")


def _extract_checkbox(prop: dict) -> Optional[bool]:
    if not prop:
        return None
    return prop.get("checkbox")


def page_to_task_summary(page: dict) -> TaskSummary:
    props = page.get("properties", {})
    return TaskSummary(
        task_id=page.get("id"),
        task_title=_extract_title(props.get(TASK_TITLE_PROP, {})),
        planned_date=_extract_date_start(props.get(TASK_PLANNED_DATE_PROP, {})),
        deadline=_extract_date_start(props.get(TASK_DEADLINE_PROP, {})),
        priority=_extract_select_name(props.get(TASK_PRIORITY_PROP, {})),
        state=_extract_select_name(props.get(TASK_STATE_PROP, {})),
        area=_extract_select_name(props.get(TASK_AREA_PROP, {})),
        url=page.get("url"),
    )


# ============================================================
#  ENDPOINTS – TASK HUB
# ============================================================

@app.post("/notion/tasks", response_model=CreateNotionTaskResponse)
def create_notion_task(body: CreateNotionTaskRequest):
    """Cria uma nova tarefa na base Task Hub."""
    try:
        props = build_notion_task_properties(body)
        page = notion.pages.create(
            parent={"database_id": NOTION_TASKS_DATABASE_ID},
            properties=props,
        )
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Erro ao criar tarefa no Notion: {e}",
        )

    return CreateNotionTaskResponse(
        task_id=page["id"],
        url=page.get("url"),
    )


@app.get("/notion/tasks", response_model=QueryTasksResponse)
def query_notion_tasks(
    planned_date: Optional[str] = Query(
        None,
        description="Data planeada (YYYY-MM-DD) para filtrar pela coluna 'Data Planeada' (principal).",
    ),
    deadline_date: Optional[str] = Query(
        None,
        description="Data limite (YYYY-MM-DD) para filtrar pela coluna 'Deadline'.",
    ),
):
    """
    Consulta tarefas na Task Hub filtradas por Data Planeada (principal) ou Deadline.
    """
    if not planned_date and not deadline_date:
        raise HTTPException(
            status_code=400,
            detail="É necessário indicar planned_date ou deadline_date.",
        )

    if planned_date:
        filter_obj = {
            "property": TASK_PLANNED_DATE_PROP,
            "date": {"equals": planned_date},
        }
    else:
        filter_obj = {
            "property": TASK_DEADLINE_PROP,
            "date": {"equals": deadline_date},
        }

    try:
        result = notion.databases.query(
            database_id=NOTION_TASKS_DATABASE_ID,
            filter=filter_obj,
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao consultar tarefas: {e}",
        )

    tasks = [page_to_task_summary(page) for page in result.get("results", [])]
    return QueryTasksResponse(tasks=tasks)


@app.patch("/notion/tasks/{taskId}", response_model=UpdateNotionTaskResponse)
def update_notion_task(
    body: UpdateNotionTaskRequest,
    taskId: str = Path(..., description="ID da tarefa no Notion"),
):
    """
    Actualiza campos de uma tarefa existente na Task Hub.
    Apenas os campos presentes no body são alterados.
    """
    properties = {}

    if body.task_title is not None:
        properties[TASK_TITLE_PROP] = {
            "title": [{"text": {"content": body.task_title}}]
        }

    if body.status is not None:
        properties[TASK_STATE_PROP] = {"select": {"name": body.status}}

    if body.priority is not None:
        properties[TASK_PRIORITY_PROP] = {"select": {"name": body.priority}}

    if body.planned_date is not None:
        properties[TASK_PLANNED_DATE_PROP] = {
            "date": {"start": body.planned_date}
        }

    if body.deadline is not None:
        properties[TASK_DEADLINE_PROP] = {"date": {"start": body.deadline}}

    if body.duration is not None:
        properties[TASK_DURATION_PROP] = {"number": body.duration}

    if body.energy_required is not None:
        properties[TASK_ENERGY_PROP] = {
            "select": {"name": body.energy_required}
        }

    if body.area is not None:
        properties[TASK_AREA_PROP] = {"select": {"name": body.area}}

    if body.notes is not None:
        properties[TASK_NOTES_PROP] = {
            "rich_text": [{"text": {"content": body.notes}}]
        }

    if not properties:
        raise HTTPException(
            status_code=400,
            detail="Nenhum campo para actualizar.",
        )

    try:
        notion.pages.update(page_id=taskId, properties=properties)
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Erro ao actualizar tarefa no Notion: {e}",
        )

    return UpdateNotionTaskResponse(
        task_id=taskId,
        updated_fields=list(properties.keys()),
    )


# ============================================================
#  MODELOS – FILMES HUB
# ============================================================

class CreateMovieRequest(BaseModel):
    title: str
    # opcional: "Visto" | "Por ver"
    status: Optional[str] = None
    # atalho booleano: True = já vi, False = por ver
    watched: Optional[bool] = None
    notes: Optional[str] = None


class MovieSummary(BaseModel):
    movie_id: str
    title: Optional[str] = None
    watched: Optional[bool] = None
    url: Optional[str] = None


class QueryMoviesResponse(BaseModel):
    movies: List[MovieSummary]


class UpdateMovieRequest(BaseModel):
    title: Optional[str] = None
    status: Optional[str] = None
    watched: Optional[bool] = None
    notes: Optional[str] = None


class UpdateMovieResponse(BaseModel):
    movie_id: str
    updated_fields: List[str]


# ============================================================
#  HELPERS – FILMES HUB
# ============================================================

def _movies_db_or_500() -> str:
    if not NOTION_MOVIES_DATABASE_ID:
        raise HTTPException(
            status_code=500,
            detail=(
                "NOTION_MOVIES_DATABASE_ID não está definido. "
                "Configura o ID da base 'Filmes Hub' nas variáveis de ambiente."
            ),
        )
    return NOTION_MOVIES_DATABASE_ID


def _resolve_watched_from_status_and_flag(
    status: Optional[str],
    watched: Optional[bool],
) -> Optional[bool]:
    """
    Converte status ("Visto" / "Por ver") + flag watched para um booleano final.
    Priority: watched > status.
    """
    if watched is not None:
        return watched

    if not status:
        return None

    s = status.strip().lower()
    if s in ("visto", "já vi", "ja vi"):
        return True
    if s in ("por ver", "não visto", "nao visto"):
        return False

    return None


def build_movie_properties(body: CreateMovieRequest):
    """
    Mapeia o pedido para as propriedades da base Filmes Hub.
    - Filme (title)
    - Já Vi (checkbox)
    - Notas (rich_text, opcional)
    """
    props = {
        MOVIE_TITLE_PROP: {
            "title": [{"text": {"content": body.title}}],
        }
    }

    watched_flag = _resolve_watched_from_status_and_flag(body.status, body.watched)
    if watched_flag is not None:
        props[MOVIE_WATCHED_PROP] = {"checkbox": watched_flag}

    if body.notes:
        props[MOVIE_NOTES_PROP] = {"rich_text": [{"text": {"content": body.notes}}]}

    return props


def page_to_movie_summary(page: dict) -> MovieSummary:
    props = page.get("properties", {})
    title = _extract_title(props.get(MOVIE_TITLE_PROP, {}))
    watched = _extract_checkbox(props.get(MOVIE_WATCHED_PROP, {}))

    return MovieSummary(
        movie_id=page.get("id"),
        title=title,
        watched=watched,
        url=page.get("url"),
    )


# ============================================================
#  ENDPOINTS – FILMES HUB
# ============================================================

@app.post("/notion/movies", response_model=MovieSummary)
def create_movie(body: CreateMovieRequest):
    """
    Cria um novo registo na base 'Filmes Hub'.
    Pode já vir marcado como visto (status='Visto' ou watched=true).
    """
    database_id = _movies_db_or_500()

    try:
        props = build_movie_properties(body)
        page = notion.pages.create(
            parent={"database_id": database_id},
            properties=props,
        )
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Erro ao criar filme no Notion: {e}",
        )

    return page_to_movie_summary(page)


@app.get("/notion/movies", response_model=QueryMoviesResponse)
def list_movies(
    watched: Optional[bool] = Query(
        None,
        description="Filtra por 'Já Vi' (true = visto, false = por ver). "
        "Se vazio, devolve todos.",
    )
):
    """
    Lista filmes da base 'Filmes Hub'.
    A Mia pode usar este endpoint para:
      - saber o que já viste (watched=true)
      - ou o que ainda tens por ver (watched=false)
      - ou então listar todos (watched omitido).
    """
    database_id = _movies_db_or_500()

    filter_obj = None
    if watched is not None:
        filter_obj = {
            "property": MOVIE_WATCHED_PROP,
            "checkbox": {"equals": watched},
        }

    try:
        if filter_obj:
            result = notion.databases.query(
                database_id=database_id,
                filter=filter_obj,
            )
        else:
            result = notion.databases.query(
                database_id=database_id,
            )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao consultar filmes: {e}",
        )

    movies = [page_to_movie_summary(page) for page in result.get("results", [])]
    return QueryMoviesResponse(movies=movies)


@app.patch("/notion/movies/{movieId}", response_model=UpdateMovieResponse)
def update_movie(
    body: UpdateMovieRequest,
    movieId: str = Path(..., description="ID do filme na base Filmes Hub"),
):
    """
    Actualiza um registo na base Filmes Hub (por ex., marcar como 'já vi').
    - Se vier watched=true/false, usamos isso directamente.
    - Se vier status='Visto'/'Por ver', convertemos para o checkbox 'Já Vi'.
    """
    _movies_db_or_500()  # garante que está configurado

    properties = {}

    if body.title is not None:
        properties[MOVIE_TITLE_PROP] = {
            "title": [{"text": {"content": body.title}}],
        }

    watched_flag = _resolve_watched_from_status_and_flag(body.status, body.watched)
    if watched_flag is not None:
        properties[MOVIE_WATCHED_PROP] = {"checkbox": watched_flag}

    if body.notes is not None:
        properties[MOVIE_NOTES_PROP] = {
            "rich_text": [{"text": {"content": body.notes}}]
        }

    if not properties:
        raise HTTPException(
            status_code=400,
            detail="Nenhum campo para actualizar.",
        )

    try:
        notion.pages.update(page_id=movieId, properties=properties)
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Erro ao actualizar filme no Notion: {e}",
        )

    return UpdateMovieResponse(
        movie_id=movieId,
        updated_fields=list(properties.keys()),
    )
