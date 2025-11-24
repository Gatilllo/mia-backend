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
#  HELPERS – genéricos
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


def _extract_date_start(prop: dict) -> Optional[str]:
    date_val = prop.get("date")
    if not date_val:
        return None
    return date_val.get("start")


def _extract_number(prop: dict) -> Optional[int]:
    return prop.get("number")


def _extract_checkbox(prop: dict) -> Optional[bool]:
    # Para propriedades checkbox (Livros Hub: "Já Li")
    return prop.get("checkbox")


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
# ============================================================

class CreateMovieRequest(BaseModel):
    title: str
    status: Optional[str] = None  # Por ver | Visto
    notes: Optional[str] = None


class MovieSummary(BaseModel):
    movie_id: str
    title: Optional[str] = None
    status: Optional[str] = None
    url: Optional[str] = None


class QueryMoviesResponse(BaseModel):
    movies: List[MovieSummary]


class UpdateMovieRequest(BaseModel):
    title: Optional[str] = None
    status: Optional[str] = None
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
            detail="NOTION_MOVIES_DATABASE_ID não está definido. "
                   "Configura o ID da base 'Filmes Hub' nas variáveis de ambiente.",
        )
    return NOTION_MOVIES_DATABASE_ID


def build_movie_properties(body: CreateMovieRequest):
    """
    Mapeia o pedido para as propriedades da base Filmes Hub.

    Ajusta os nomes das propriedades aos da tua base Notion.
    Aqui assumimos:
      - Título (title)
      - Estado (select)
      - Notas (rich_text)
    """
    props = {
        "Título": {
            "title": [{"text": {"content": body.title}}],
        }
    }

    if body.status:
        props["Estado"] = {"select": {"name": body.status}}

    if body.notes:
        props["Notas"] = {"rich_text": [{"text": {"content": body.notes}}]}

    return props


def page_to_movie_summary(page: dict) -> MovieSummary:
    props = page.get("properties", {})
    title = _extract_title(props.get("Título", {}))
    status = _extract_select_name(props.get("Estado", {}))

    return MovieSummary(
        movie_id=page.get("id"),
        title=title,
        status=status,
        url=page.get("url"),
    )


# ============================================================
#  ENDPOINTS – FILMES HUB
# ============================================================

@app.post("/notion/movies", response_model=MovieSummary)
def create_movie(body: CreateMovieRequest):
    """
    Cria um novo registo na base 'Filmes Hub'.
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
    status: Optional[str] = Query(
        None,
        description="Filtra por Estado (ex.: 'Por ver', 'Visto'). Se vazio, devolve todos.",
    )
):
    """
    Lista filmes da base 'Filmes Hub'.
    A Mia pode usar este endpoint para sugerir um filme com base no contexto.
    """
    database_id = _movies_db_or_500()

    filter_obj = None
    if status:
        filter_obj = {
            "property": "Estado",
            "select": {"equals": status},
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
    Actualiza um registo na base Filmes Hub (por ex., marcar como 'Visto').
    """
    _movies_db_or_500()  # só para garantir que está configurado

    properties = {}

    if body.title is not None:
        properties["Título"] = {
            "title": [{"text": {"content": body.title}}],
        }

    if body.status is not None:
        properties["Estado"] = {"select": {"name": body.status}}

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


# ============================================================
#  MODELOS – LIVROS HUB
# ============================================================

class CreateBookRequest(BaseModel):
    book_title: str
    read: Optional[bool] = None
    notes: Optional[str] = None


class BookSummary(BaseModel):
    book_id: str
    title: Optional[str] = None
    read: Optional[bool] = None
    url: Optional[str] = None


class QueryBooksResponse(BaseModel):
    books: List[BookSummary]


class UpdateBookRequest(BaseModel):
    book_title: Optional[str] = None
    read: Optional[bool] = None
    notes: Optional[str] = None


class UpdateBookResponse(BaseModel):
    book_id: str
    updated_fields: List[str]


# ============================================================
#  HELPERS – LIVROS HUB
# ============================================================

def _books_db_or_500() -> str:
    if not NOTION_BOOKS_DATABASE_ID:
        raise HTTPException(
            status_code=500,
            detail="NOTION_BOOKS_DATABASE_ID não está definido. "
                   "Configura o ID da base 'Livros Hub' nas variáveis de ambiente.",
        )
    return NOTION_BOOKS_DATABASE_ID


def build_book_properties(body: CreateBookRequest):
    """
    Mapeia o pedido para as propriedades da base Livros Hub.

    Na base Livros Hub assumimos:
      - Livro (title)
      - Já Li (checkbox)
      - Notas (rich_text, opcional)
    """
    props = {
        "Livro": {
            "title": [{"text": {"content": body.book_title}}],
        }
    }

    if body.read is not None:
        props["Já Li"] = {"checkbox": bool(body.read)}

    if body.notes:
        props["Notas"] = {"rich_text": [{"text": {"content": body.notes}}]}

    return props


def page_to_book_summary(page: dict) -> BookSummary:
    props = page.get("properties", {})
    title = _extract_title(props.get("Livro", {}))
    read = _extract_checkbox(props.get("Já Li", {}))

    return BookSummary(
        book_id=page.get("id"),
        title=title,
        read=read,
        url=page.get("url"),
    )


# ============================================================
#  ENDPOINTS – LIVROS HUB
# ============================================================

@app.post("/notion/books", response_model=BookSummary)
def create_book(body: CreateBookRequest):
    """
    Cria um novo registo na base 'Livros Hub'.
    """
    database_id = _books_db_or_500()

    try:
        props = build_book_properties(body)
        page = notion.pages.create(
            parent={"database_id": database_id},
            properties=props,
        )
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Erro ao criar livro no Notion: {e}",
        )

    return page_to_book_summary(page)


@app.get("/notion/books", response_model=QueryBooksResponse)
def list_books(
    read: Optional[bool] = Query(
        None,
        description="Se true, só livros já lidos; se false, só livros por ler; se omitido, todos.",
    )
):
    """
    Lista livros da base 'Livros Hub'.
    """
    database_id = _books_db_or_500()

    filter_obj = None
    if read is not None:
        filter_obj = {
            "property": "Já Li",
            "checkbox": {"equals": bool(read)},
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
            detail=f"Erro ao consultar livros: {e}",
        )

    books = [page_to_book_summary(page) for page in result.get("results", [])]
    return QueryBooksResponse(books=books)


@app.patch("/notion/books/{bookId}", response_model=UpdateBookResponse)
def update_book(
    body: UpdateBookRequest,
    bookId: str = Path(..., description="ID do livro na base Livros Hub"),
):
    """
    Actualiza um registo na base Livros Hub (por ex., marcar como lido).
    """
    _books_db_or_500()  # só para garantir que está configurado

    properties = {}

    if body.book_title is not None:
        properties["Livro"] = {
            "title": [{"text": {"content": body.book_title}}],
        }

    if body.read is not None:
        properties["Já Li"] = {"checkbox": bool(body.read)}

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
        notion.pages.update(page_id=bookId, properties=properties)
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Erro ao actualizar livro no Notion: {e}",
        )

    return UpdateBookResponse(
        book_id=bookId,
        updated_fields=list(properties.keys()),
    )
