import os
from typing import Optional, List

from fastapi import FastAPI, HTTPException, Path, Query
from pydantic import BaseModel
from dotenv import load_dotenv
from notion_client import Client as NotionClient

# Carregar variáveis de ambiente
load_dotenv()

NOTION_API_KEY = os.getenv("NOTION_API_KEY")
NOTION_TASKS_DATABASE_ID = os.getenv("NOTION_TASKS_DATABASE_ID")
NOTION_MOVIES_DATABASE_ID = os.getenv("NOTION_MOVIES_DATABASE_ID")

if NOTION_API_KEY is None or NOTION_TASKS_DATABASE_ID is None:
    raise RuntimeError(
        "NOTION_API_KEY e NOTION_TASKS_DATABASE_ID têm de estar definidos nas variáveis de ambiente."
    )

# Cliente oficial do Notion
notion = NotionClient(auth=NOTION_API_KEY)

app = FastAPI(title="Mia Notion API")


# ============================================================
#                       MODELOS TASKS
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
#                       MODELOS FILMES
# ============================================================

class CreateMovieRequest(BaseModel):
    movie_title: str
    categories: Optional[List[str]] = None      # Multi-select
    energy_required: Optional[str] = None       # Alta | Média | Baixa
    mood: Optional[str] = None                  # Relaxar, Divertido, Intenso, etc.
    duration: Optional[int] = None              # minutos
    watched: Optional[bool] = None
    watched_date: Optional[str] = None          # YYYY-MM-DD
    rating: Optional[float] = None
    notes: Optional[str] = None


class CreateMovieResponse(BaseModel):
    movie_id: str
    url: Optional[str]


class UpdateMovieRequest(BaseModel):
    movie_title: Optional[str] = None
    categories: Optional[List[str]] = None
    energy_required: Optional[str] = None
    mood: Optional[str] = None
    duration: Optional[int] = None
    watched: Optional[bool] = None
    watched_date: Optional[str] = None
    rating: Optional[float] = None
    notes: Optional[str] = None


class UpdateMovieResponse(BaseModel):
    movie_id: str
    updated_fields: List[str]


class MovieSummary(BaseModel):
    movie_id: str
    movie_title: Optional[str] = None
    categories: List[str] = []
    energy_required: Optional[str] = None
    mood: Optional[str] = None
    duration: Optional[int] = None
    watched: Optional[bool] = None
    watched_date: Optional[str] = None
    rating: Optional[float] = None
    notes: Optional[str] = None
    url: Optional[str] = None


class QueryMoviesResponse(BaseModel):
    movies: List[MovieSummary]


# ============================================================
#                          HELPERS COMUNS
# ============================================================

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


def _extract_multi_select_names(prop: dict) -> List[str]:
    ms = prop.get("multi_select")
    if not ms:
        return []
    return [item.get("name", "") for item in ms]


def _extract_date_start(prop: dict) -> Optional[str]:
    date_val = prop.get("date")
    if not date_val:
        return None
    return date_val.get("start")


def _extract_number(prop: dict) -> Optional[int]:
    return prop.get("number")


def _extract_checkbox(prop: dict) -> Optional[bool]:
    return prop.get("checkbox")


def _extract_rich_text(prop: dict) -> Optional[str]:
    rt = prop.get("rich_text")
    if not rt:
        return None
    return "".join(part.get("plain_text", "") for part in rt)


# ============================================================
#                        HELPERS TASKS
# ============================================================

def build_notion_task_properties(body: CreateNotionTaskRequest):
    """
    Constrói o dicionário de propriedades exactamente com os
    nomes de colunas da base Task Hub 2.0 no Notion.
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


def page_to_task_summary(page: dict) -> TaskSummary:
    props = page.get("properties", {})
    return TaskSummary(
        task_id=page.get("id"),
        task_title=_extract_title(props.get("Tarefa", {})),
        planned_date=_extract_date_start(props.get("Data Planeada", {})),
        deadline=_extract_date_start(props.get("Deadline", {})),
        priority=_extract_select_name(props.get("Prioridade", {})),
        state=_extract_select_name(props.get("Estado", {})),
        area=_extract_select_name(props.get("Área da Vida", {})),
        url=page.get("url"),
    )


# ============================================================
#                        HELPERS FILMES
# ============================================================

def build_notion_movie_properties(body: CreateMovieRequest):
    """
    Constrói o dicionário de propriedades para a base Filmes Hub.
    """
    props = {
        "Filme": {
            "title": [{"text": {"content": body.movie_title}}],
        }
    }

    if body.categories:
        props["Categoria"] = {
            "multi_select": [{"name": c} for c in body.categories]
        }

    if body.energy_required:
        props["Energia Necessária"] = {
            "select": {"name": body.energy_required}
        }

    if body.mood:
        props["Mood Ideal"] = {"select": {"name": body.mood}}

    if body.duration is not None:
        props["Duração"] = {"number": body.duration}

    if body.watched is not None:
        props["Já Vi"] = {"checkbox": body.watched}

    if body.watched_date:
        props["Data Visto"] = {"date": {"start": body.watched_date}}

    if body.rating is not None:
        props["Avaliação"] = {"number": body.rating}

    if body.notes:
        props["Notas"] = {"rich_text": [{"text": {"content": body.notes}}]}

    return props


def page_to_movie_summary(page: dict) -> MovieSummary:
    props = page.get("properties", {})
    return MovieSummary(
        movie_id=page.get("id"),
        movie_title=_extract_title(props.get("Filme", {})),
        categories=_extract_multi_select_names(props.get("Categoria", {})),
        energy_required=_extract_select_name(props.get("Energia Necessária", {})),
        mood=_extract_select_name(props.get("Mood Ideal", {})),
        duration=_extract_number(props.get("Duração", {})),
        watched=_extract_checkbox(props.get("Já Vi", {})),
        watched_date=_extract_date_start(props.get("Data Visto", {})),
        rating=_extract_number(props.get("Avaliação", {})),
        notes=_extract_rich_text(props.get("Notas", {})),
        url=page.get("url"),
    )


# ============================================================
#                         ENDPOINTS TASKS
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
        description="Data planeada (YYYY-MM-DD) para filtrar pela coluna 'Data Planeada'.",
    ),
    deadline_date: Optional[str] = Query(
        None,
        description="Data limite (YYYY-MM-DD) para filtrar pela coluna 'Deadline'.",
    ),
):
    """
    Consulta tarefas na Task Hub 2.0 filtradas por Data Planeada (principal) ou Deadline.
    """
    if not planned_date and not deadline_date:
        raise HTTPException(
            status_code=400,
            detail="É necessário indicar planned_date ou deadline_date.",
        )

    if planned_date:
        filter_obj = {
            "property": "Data Planeada",
            "date": {"equals": planned_date},
        }
    else:
        filter_obj = {
            "property": "Deadline",
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
    Actualiza campos de uma tarefa existente na Task Hub 2.0.
    Apenas os campos presentes no body são alterados.
    """
    properties = {}

    if body.task_title is not None:
        properties["Tarefa"] = {
            "title": [{"text": {"content": body.task_title}}]
        }

    if body.status is not None:
        properties["Estado"] = {"select": {"name": body.status}}

    if body.priority is not None:
        properties["Prioridade"] = {"select": {"name": body.priority}}

    if body.planned_date is not None:
        properties["Data Planeada"] = {
            "date": {"start": body.planned_date}
        }

    if body.deadline is not None:
        properties["Deadline"] = {"date": {"start": body.deadline}}

    if body.duration is not None:
        properties["Duração Estimada (min)"] = {
            "number": body.duration
        }

    if body.energy_required is not None:
        properties["Energia Necessária"] = {
            "select": {"name": body.energy_required}
        }

    if body.area is not None:
        properties["Área da Vida"] = {"select": {"name": body.area}}

    if body.notes is not None:
        properties["Notas"] = {
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
#                         ENDPOINTS FILMES
# ============================================================

@app.post("/notion/movies", response_model=CreateMovieResponse)
def create_notion_movie(body: CreateMovieRequest):
    """
    Cria um novo filme na base Filmes Hub.
    """
    if NOTION_MOVIES_DATABASE_ID is None:
        raise HTTPException(
            status_code=500,
            detail="NOTION_MOVIES_DATABASE_ID não está definido nas variáveis de ambiente.",
        )

    try:
        props = build_notion_movie_properties(body)
        page = notion.pages.create(
            parent={"database_id": NOTION_MOVIES_DATABASE_ID},
            properties=props,
        )
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Erro ao criar filme no Notion: {e}",
        )

    return CreateMovieResponse(
        movie_id=page["id"],
        url=page.get("url"),
    )


@app.get("/notion/movies", response_model=QueryMoviesResponse)
def query_notion_movies(
    mood: Optional[str] = Query(
        None, description="Mood ideal (Relaxar, Divertido, Intenso, etc.)."
    ),
    energy_required: Optional[str] = Query(
        None, description="Energia necessária (Alta, Média, Baixa)."
    ),
    max_duration: Optional[int] = Query(
        None, description="Duração máxima em minutos."
    ),
    only_unwatched: bool = Query(
        True, description="Se True, devolve apenas filmes ainda não vistos."
    ),
):
    """
    Consulta filmes na base Filmes Hub, filtrando por mood, energia, duração e se já foram vistos.
    """
    if NOTION_MOVIES_DATABASE_ID is None:
        raise HTTPException(
            status_code=500,
            detail="NOTION_MOVIES_DATABASE_ID não está definido nas variáveis de ambiente.",
        )

    filters = []

    if mood:
        filters.append(
            {
                "property": "Mood Ideal",
                "select": {"equals": mood},
            }
        )

    if energy_required:
        filters.append(
            {
                "property": "Energia Necessária",
                "select": {"equals": energy_required},
            }
        )

    if max_duration is not None:
        filters.append(
            {
                "property": "Duração",
                "number": {"less_than_or_equal_to": max_duration},
            }
        )

    if only_unwatched:
        filters.append(
            {
                "property": "Já Vi",
                "checkbox": {"equals": False},
            }
        )

    filter_obj: Optional[dict] = None
    if len(filters) == 1:
        filter_obj = filters[0]
    elif len(filters) > 1:
        filter_obj = {"and": filters}

    try:
        query_args = {"database_id": NOTION_MOVIES_DATABASE_ID}
        if filter_obj is not None:
            query_args["filter"] = filter_obj

        result = notion.databases.query(**query_args)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao consultar filmes: {e}",
        )

    movies = [page_to_movie_summary(page) for page in result.get("results", [])]
    return QueryMoviesResponse(movies=movies)


@app.patch("/notion/movies/{movieId}", response_model=UpdateMovieResponse)
def update_notion_movie(
    body: UpdateMovieRequest,
    movieId: str = Path(..., description="ID do filme no Notion"),
):
    """
    Actualiza campos de um filme existente na base Filmes Hub.
    Apenas os campos presentes no body são alterados.
    """
    if NOTION_MOVIES_DATABASE_ID is None:
        raise HTTPException(
            status_code=500,
            detail="NOTION_MOVIES_DATABASE_ID não está definido nas variáveis de ambiente.",
        )

    properties = {}

    if body.movie_title is not None:
        properties["Filme"] = {
            "title": [{"text": {"content": body.movie_title}}]
        }

    if body.categories is not None:
        properties["Categoria"] = {
            "multi_select": [{"name": c} for c in body.categories]
        }

    if body.energy_required is not None:
        properties["Energia Necessária"] = {
            "select": {"name": body.energy_required}
        }

    if body.mood is not None:
        properties["Mood Ideal"] = {"select": {"name": body.mood}}

    if body.duration is not None:
        properties["Duração"] = {"number": body.duration}

    if body.watched is not None:
        properties["Já Vi"] = {"checkbox": body.watched}

    if body.watched_date is not None:
        properties["Data Visto"] = {"date": {"start": body.watched_date}}

    if body.rating is not None:
        properties["Avaliação"] = {"number": body.rating}

    if body.notes is not None:
        properties["Notas"] = {
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
