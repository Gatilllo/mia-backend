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

if NOTION_API_KEY is None:
    raise RuntimeError("NOTION_API_KEY tem de estar definido nas variáveis de ambiente.")

if NOTION_TASKS_DATABASE_ID is None:
    raise RuntimeError("NOTION_TASKS_DATABASE_ID tem de estar definido nas variáveis de ambiente.")

# Cliente oficial do Notion
notion = NotionClient(auth=NOTION_API_KEY)

app = FastAPI(title="Mia Notion API")


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
    """
    Constrói o dicionário de propriedades exactamente com os
    nomes de colunas da base Task Hub no Notion.
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


def _extract_number(prop: dict) -> Optional[float]:
    return prop.get("number")


def _extract_checkbox(prop: dict) -> Optional[bool]:
    # Notion devolve {"checkbox": true/false}
    return prop.get("checkbox")


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
#  ENDPOINTS – TASK HUB
# ============================================================

@app.post("/notion/tasks", response_model=CreateNotionTaskResponse)
def create_notion_task(body: CreateNotionTaskRequest):
    """
    Cria uma nova tarefa na base Task Hub.
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
        description="Data planeada (YYYY-MM-DD) para filtrar pela coluna 'Data Planeada' (principal).",
    ),
    deadline_date: Optional[str] = Query(
        None,
        description="Data limite (YYYY-MM-DD) para filtrar pela coluna 'Deadline'.",
    ),
):
    """
    Consulta tarefas na Task Hub filtradas por Data Planeada (principal) ou Deadline.

    - Usa planned_date para perguntas do tipo "tarefas para hoje/amanhã/dia X".
    - Usa deadline_date apenas para perguntas sobre prazos de conclusão de tarefas.
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
    Actualiza campos de uma tarefa existente na Task Hub.
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
#  MODELOS – FILMES HUB
#  (alinhado com as colunas: Filme, Categoria, Energia Necessária,
#   Mood Ideal, Duração, Já Vi, Data Visto, Avaliação)
# ============================================================

class CreateMovieRequest(BaseModel):
    title: str
    category: Optional[str] = None           # ex.: Drama, Comédia, Documentário...
    energy_required: Optional[str] = None    # ex.: Baixa, Média, Alta
    ideal_mood: Optional[str] = None         # ex.: Motivado, Cansado, Família...
    duration: Optional[int] = None           # minutos
    watched: Optional[bool] = None           # mapeia para checkbox "Já Vi"
    watched_date: Optional[str] = None       # YYYY-MM-DD -> "Data Visto"
    rating: Optional[float] = None           # Avaliação numérica (0–10, por ex.)


class MovieSummary(BaseModel):
    movie_id: str
    title: Optional[str] = None
    category: Optional[str] = None
    energy_required: Optional[str] = None
    ideal_mood: Optional[str] = None
    duration: Optional[int] = None
    watched: Optional[bool] = None
    watched_date: Optional[str] = None
    rating: Optional[float] = None
    url: Optional[str] = None


class QueryMoviesResponse(BaseModel):
    movies: List[MovieSummary]


class UpdateMovieRequest(BaseModel):
    title: Optional[str] = None
    category: Optional[str] = None
    energy_required: Optional[str] = None
    ideal_mood: Optional[str] = None
    duration: Optional[int] = None
    watched: Optional[bool] = None
    watched_date: Optional[str] = None
    rating: Optional[float] = None


class UpdateMovieResponse(BaseModel):
    movie_id: str
    updated_fields: List[str]


class BulkCreateMoviesRequest(BaseModel):
    movies: List[CreateMovieRequest]


class BulkCreateMoviesResponse(BaseModel):
    movies: List[MovieSummary]


# ============================================================
#  HELPERS – FILMES HUB
# ============================================================

def _movies_db_or_500() -> str:
    if not NOTION_MOVIES_DATABASE_ID:
        raise HTTPException(
            status_code=500,
            detail="NOTION_MOVIES_DATABASE_ID não está definido. "
                   "Configura o ID da base 'Filmes Hub' nas variáveis de ambiente.",
        )
    return NOTION_MOVIES_DATABASE_ID


def build_movie_properties(body: CreateMovieRequest):
    """
    Mapeia o pedido para as propriedades da base Filmes Hub.

    Colunas da base:
      - Filme (title)
      - Categoria (select)
      - Energia Necessária (select)
      - Mood Ideal (select)
      - Duração (number)
      - Já Vi (checkbox)
      - Data Visto (date)
      - Avaliação (number)
    """
    props = {
        "Filme": {
            "title": [{"text": {"content": body.title}}],
        }
    }

    if body.category:
        props["Categoria"] = {"select": {"name": body.category}}

    if body.energy_required:
        props["Energia Necessária"] = {"select": {"name": body.energy_required}}

    if body.ideal_mood:
        props["Mood Ideal"] = {"select": {"name": body.ideal_mood}}

    if body.duration is not None:
        props["Duração"] = {"number": body.duration}

    if body.watched is not None:
        props["Já Vi"] = {"checkbox": body.watched}

    if body.watched_date:
        props["Data Visto"] = {"date": {"start": body.watched_date}}

    if body.rating is not None:
        props["Avaliação"] = {"number": body.rating}

    return props


def page_to_movie_summary(page: dict) -> MovieSummary:
    props = page.get("properties", {})

    title = _extract_title(props.get("Filme", {}))
    category = _extract_select_name(props.get("Categoria", {}))
    energy_required = _extract_select_name(props.get("Energia Necessária", {}))
    ideal_mood = _extract_select_name(props.get("Mood Ideal", {}))
    duration = _extract_number(props.get("Duração", {}))
    watched = _extract_checkbox(props.get("Já Vi", {}))
    watched_date = _extract_date_start(props.get("Data Visto", {}))
    rating = _extract_number(props.get("Avaliação", {}))

    # duration e rating vêm como float da API, aqui converto duration para int se existir
    duration_int: Optional[int] = int(duration) if duration is not None else None

    return MovieSummary(
        movie_id=page.get("id"),
        title=title,
        category=category,
        energy_required=energy_required,
        ideal_mood=ideal_mood,
        duration=duration_int,
        watched=watched,
        watched_date=watched_date,
        rating=rating,
        url=page.get("url"),
    )


# ============================================================
#  ENDPOINTS – FILMES HUB
# ============================================================

@app.post("/notion/movies", response_model=MovieSummary)
def create_movie(body: CreateMovieRequest):
    """
    Cria um novo registo na base 'Filmes Hub'.

    Usado, por exemplo, quando o utilizador passa um único filme
    (ou quando a Mia decide criar por partes).
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


@app.post("/notion/movies/bulk", response_model=BulkCreateMoviesResponse)
def create_movies_bulk(body: BulkCreateMoviesRequest):
    """
    Cria vários filmes de uma só vez na base 'Filmes Hub'.
    A Mia pode usar isto quando extrai uma lista grande (por ex. de um post-it).
    """
    database_id = _movies_db_or_500()

    created: List[MovieSummary] = []
    try:
        for movie in body.movies:
            props = build_movie_properties(movie)
            page = notion.pages.create(
                parent={"database_id": database_id},
                properties=props,
            )
            created.append(page_to_movie_summary(page))
    except Exception as e:
        # Se der erro a meio, devolve o que já foi criado e a mensagem
        raise HTTPException(
            status_code=400,
            detail=f"Erro ao criar filmes no Notion: {e}",
        )

    return BulkCreateMoviesResponse(movies=created)


@app.get("/notion/movies", response_model=QueryMoviesResponse)
def list_movies(
    watched: Optional[bool] = Query(
        None,
        description="Filtra por 'Já Vi' (true/false). Se vazio, devolve todos.",
    )
):
    """
    Lista filmes da base 'Filmes Hub'.
    A Mia pode usar este endpoint para sugerir um filme com base no contexto / energia.
    """
    database_id = _movies_db_or_500()

    filter_obj = None
    if watched is not None:
        filter_obj = {
            "property": "Já Vi",
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
    Actualiza um registo na base Filmes Hub (por ex., marcar como 'Já Vi').
    """
    _movies_db_or_500()  # só para garantir que está configurado

    properties = {}

    if body.title is not None:
        properties["Filme"] = {
            "title": [{"text": {"content": body.title}}],
        }

    if body.category is not None:
        properties["Categoria"] = {"select": {"name": body.category}}

    if body.energy_required is not None:
        properties["Energia Necessária"] = {
            "select": {"name": body.energy_required}
        }

    if body.ideal_mood is not None:
        properties["Mood Ideal"] = {"select": {"name": body.ideal_mood}}

    if body.duration is not None:
        properties["Duração"] = {"number": body.duration}

    if body.watched is not None:
        properties["Já Vi"] = {"checkbox": body.watched}

    if body.watched_date is not None:
        properties["Data Visto"] = {"date": {"start": body.watched_date}}

    if body.rating is not None:
        properties["Avaliação"] = {"number": body.rating}

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
