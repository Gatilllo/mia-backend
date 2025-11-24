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

if NOTION_API_KEY is None:
    raise RuntimeError("NOTION_API_KEY tem de estar definido nas variáveis de ambiente.")

if NOTION_TASKS_DATABASE_ID is None:
    raise RuntimeError("NOTION_TASKS_DATABASE_ID tem de estar definido nas variáveis de ambiente.")

# Cliente oficial do Notion
notion = NotionClient(auth=NOTION_API_KEY)

app = FastAPI(title="Mia Notion API")


# ============================================================
#  HELPERS GENÉRICOS
# ============================================================

def _extract_title(prop: dict) -> Optional[str]:
    title = prop.get("title")
    if not title:
        return None
    return "".join(part.get("plain_text", "") for part in title)


def _extract_rich_text(prop: dict) -> Optional[str]:
    rt = prop.get("rich_text")
    if not rt:
        return None
    return "".join(part.get("plain_text", "") for part in rt)


def _extract_select_name(prop: dict) -> Optional[str]:
    sel = prop.get("select")
    if not sel:
        return None
    return sel.get("name")


def _extract_multi_select(prop: dict) -> List[str]:
    ms = prop.get("multi_select") or []
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


# ----------------- HELPERS TASKS -----------------

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


# ----------------- ENDPOINTS TASKS -----------------

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


# ----------------- HELPERS FILMES -----------------

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

    Na base Filmes Hub:
      - Filme (title)
      - Estado (select)
      - Notas (rich_text, opcional)
    """
    props = {
        "Filme": {
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
    title = _extract_title(props.get("Filme", {}))
    status = _extract_select_name(props.get("Estado", {}))

    return MovieSummary(
        movie_id=page.get("id"),
        title=title,
        status=status,
        url=page.get("url"),
    )


# ----------------- ENDPOINTS FILMES -----------------

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
    _movies_db_or_500()  # apenas valida que está configurado

    properties = {}

    if body.title is not None:
        properties["Filme"] = {
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
    title: str
    author: Optional[str] = None
    status: Optional[str] = None  # Por ler | A ler | Lido
    notes: Optional[str] = None


class BookSummary(BaseModel):
    book_id: str
    title: Optional[str] = None
    author: Optional[str] = None
    status: Optional[str] = None
    url: Optional[str] = None


class QueryBooksResponse(BaseModel):
    books: List[BookSummary]


class UpdateBookRequest(BaseModel):
    title: Optional[str] = None
    author: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = None


class UpdateBookResponse(BaseModel):
    book_id: str
    updated_fields: List[str]


# ----------------- HELPERS LIVROS -----------------

def _books_db_or_500() -> str:
    if not NOTION_BOOKS_DATABASE_ID:
        raise HTTPException(
            status_code=500,
            detail="NOTION_BOOKS_DATABASE_ID não está definido. "
                   "Configura o ID da base 'Livros Hub' nas variáveis de ambiente.",
        )
    return NOTION_BOOKS_DATABASE_ID


def build_book_properties(body: CreateBookRequest):
    props = {
        "Livro": {
            "title": [{"text": {"content": body.title}}],
        }
    }

    if body.author:
        props["Autor"] = {"rich_text": [{"text": {"content": body.author}}]}

    if body.status:
        props["Estado"] = {"select": {"name": body.status}}

    if body.notes:
        props["Notas"] = {"rich_text": [{"text": {"content": body.notes}}]}

    return props


def page_to_book_summary(page: dict) -> BookSummary:
    props = page.get("properties", {})
    return BookSummary(
        book_id=page.get("id"),
        title=_extract_title(props.get("Livro", {})),
        author=_extract_rich_text(props.get("Autor", {})),
        status=_extract_select_name(props.get("Estado", {})),
        url=page.get("url"),
    )


# ----------------- ENDPOINTS LIVROS -----------------

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
    status: Optional[str] = Query(
        None,
        description="Filtra por Estado (ex.: 'Por ler', 'A ler', 'Lido'). Se vazio, devolve todos.",
    )
):
    """
    Lista livros da base 'Livros Hub'.
    """
    database_id = _books_db_or_500()

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
    Actualiza um registo na base Livros Hub.
    """
    _books_db_or_500()  # apenas valida que está configurado

    properties = {}

    if body.title is not None:
        properties["Livro"] = {
            "title": [{"text": {"content": body.title}}],
        }

    if body.author is not None:
        properties["Autor"] = {
            "rich_text": [{"text": {"content": body.author}}]
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


# ============================================================
#  MODELOS – FRASES / QUOTES HUB
# ============================================================

class CreateQuoteRequest(BaseModel):
    text: str
    author: Optional[str] = None
    source: Optional[str] = None
    tags: Optional[List[str]] = None
    favorite: Optional[bool] = None


class QuoteSummary(BaseModel):
    quote_id: str
    text: Optional[str] = None
    author: Optional[str] = None
    source: Optional[str] = None
    tags: List[str] = []
    favorite: Optional[bool] = None
    url: Optional[str] = None


class QueryQuotesResponse(BaseModel):
    quotes: List[QuoteSummary]


class UpdateQuoteRequest(BaseModel):
    text: Optional[str] = None
    author: Optional[str] = None
    source: Optional[str] = None
    tags: Optional[List[str]] = None
    favorite: Optional[bool] = None


class UpdateQuoteResponse(BaseModel):
    quote_id: str
    updated_fields: List[str]


# ----------------- HELPERS QUOTES -----------------

def _quotes_db_or_500() -> str:
    if not NOTION_QUOTES_DATABASE_ID:
        raise HTTPException(
            status_code=500,
            detail="NOTION_QUOTES_DATABASE_ID não está definido. "
                   "Configura o ID da base 'Frases Hub' nas variáveis de ambiente.",
        )
    return NOTION_QUOTES_DATABASE_ID


def build_quote_properties(body: CreateQuoteRequest):
    props = {
        "Frase": {
            "title": [{"text": {"content": body.text}}],
        }
    }

    if body.author:
        props["Autor"] = {"rich_text": [{"text": {"content": body.author}}]}

    if body.source:
        props["Fonte"] = {"rich_text": [{"text": {"content": body.source}}]}

    if body.tags:
        props["Tags"] = {
            "multi_select": [{"name": tag} for tag in body.tags]
        }

    if body.favorite is not None:
        props["Favorita"] = {"checkbox": body.favorite}

    return props


def page_to_quote_summary(page: dict) -> QuoteSummary:
    props = page.get("properties", {})
    return QuoteSummary(
        quote_id=page.get("id"),
        text=_extract_title(props.get("Frase", {})),
        author=_extract_rich_text(props.get("Autor", {})),
        source=_extract_rich_text(props.get("Fonte", {})),
        tags=_extract_multi_select(props.get("Tags", {})),
        favorite=_extract_checkbox(props.get("Favorita", {})),
        url=page.get("url"),
    )


# ----------------- ENDPOINTS QUOTES -----------------

@app.post("/notion/quotes", response_model=QuoteSummary)
def create_quote(body: CreateQuoteRequest):
    """
    Cria uma nova frase na base 'Frases Hub'.
    """
    database_id = _quotes_db_or_500()

    try:
        props = build_quote_properties(body)
        page = notion.pages.create(
            parent={"database_id": database_id},
            properties=props,
        )
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Erro ao criar frase no Notion: {e}",
        )

    return page_to_quote_summary(page)


@app.get("/notion/quotes", response_model=QueryQuotesResponse)
def list_quotes(
    author: Optional[str] = Query(
        None,
        description="Filtra por autor (texto contém).",
    ),
    favorite: Optional[bool] = Query(
        None,
        description="Se true, apenas frases marcadas como favoritas.",
    ),
):
    """
    Lista frases da base 'Frases Hub'.
    """
    database_id = _quotes_db_or_500()

    # Construção flexível do filtro
    filters = []

    if author:
        filters.append(
            {
                "property": "Autor",
                "rich_text": {"contains": author},
            }
        )

    if favorite is not None:
        filters.append(
            {
                "property": "Favorita",
                "checkbox": {"equals": favorite},
            }
        )

    filter_obj = None
    if len(filters) == 1:
        filter_obj = filters[0]
    elif len(filters) > 1:
        filter_obj = {"and": filters}

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
            detail=f"Erro ao consultar frases: {e}",
        )

    quotes = [page_to_quote_summary(page) for page in result.get("results", [])]
    return QueryQuotesResponse(quotes=quotes)


@app.patch("/notion/quotes/{quoteId}", response_model=UpdateQuoteResponse)
def update_quote(
    body: UpdateQuoteRequest,
    quoteId: str = Path(..., description="ID da frase na base Frases Hub"),
):
    """
    Actualiza um registo na base Frases Hub.
    """
    _quotes_db_or_500()  # apenas valida que está configurado

    properties = {}

    if body.text is not None:
        properties["Frase"] = {
            "title": [{"text": {"content": body.text}}],
        }

    if body.author is not None:
        properties["Autor"] = {
            "rich_text": [{"text": {"content": body.author}}]
        }

    if body.source is not None:
        properties["Fonte"] = {
            "rich_text": [{"text": {"content": body.source}}]
        }

    if body.tags is not None:
        properties["Tags"] = {
            "multi_select": [{"name": tag} for tag in body.tags]
        }

    if body.favorite is not None:
        properties["Favorita"] = {"checkbox": body.favorite}

    if not properties:
        raise HTTPException(
            status_code=400,
            detail="Nenhum campo para actualizar.",
        )

    try:
        notion.pages.update(page_id=quoteId, properties=properties)
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Erro ao actualizar frase no Notion: {e}",
        )

    return UpdateQuoteResponse(
        quote_id=quoteId,
        updated_fields=list(properties.keys()),
    )


# ============================================================
#  MODELOS – IDEIAS & NOTAS HUB
# ============================================================

class CreateNoteRequest(BaseModel):
    title: str
    category: Optional[str] = None          # Ideia | Reflexão | Lembrete | etc. (select "Categoria")
    tags: Optional[List[str]] = None        # multi-select "Tags"
    context: Optional[str] = None           # rich_text "Contexto"
    source: Optional[str] = None            # rich_text "Fonte"
    favorite: Optional[bool] = None         # checkbox "Favorito"


class NoteSummary(BaseModel):
    note_id: str
    title: Optional[str] = None
    category: Optional[str] = None
    tags: List[str] = []
    favorite: Optional[bool] = None
    url: Optional[str] = None


class QueryNotesResponse(BaseModel):
    notes: List[NoteSummary]


class UpdateNoteRequest(BaseModel):
    title: Optional[str] = None
    category: Optional[str] = None
    tags: Optional[List[str]] = None
    context: Optional[str] = None
    source: Optional[str] = None
    favorite: Optional[bool] = None


class UpdateNoteResponse(BaseModel):
    note_id: str
    updated_fields: List[str]


# ----------------- HELPERS NOTAS -----------------

def _notes_db_or_500() -> str:
    if not NOTION_NOTES_DATABASE_ID:
        raise HTTPException(
            status_code=500,
            detail="NOTION_NOTES_DATABASE_ID não está definido. "
                   "Configura o ID da base 'Ideias & Notas Hub' nas variáveis de ambiente.",
        )
    return NOTION_NOTES_DATABASE_ID


def build_note_properties(body: CreateNoteRequest):
    """
    Mapeia o pedido para as propriedades da base Ideias & Notas Hub.

    Espera que a base tenha (podes ajustar no Notion):
      - Nota (title)
      - Categoria (select)
      - Tags (multi-select)
      - Contexto (rich_text)
      - Fonte (rich_text)
      - Favorito (checkbox)
    """
    props = {
        "Nota": {
            "title": [{"text": {"content": body.title}}],
        }
    }

    if body.category:
        props["Categoria"] = {"select": {"name": body.category}}

    if body.tags:
        props["Tags"] = {
            "multi_select": [{"name": tag} for tag in body.tags]
        }

    if body.context:
        props["Contexto"] = {"rich_text": [{"text": {"content": body.context}}]}

    if body.source:
        props["Fonte"] = {"rich_text": [{"text": {"content": body.source}}]}

    if body.favorite is not None:
        props["Favorito"] = {"checkbox": body.favorite}

    return props


def page_to_note_summary(page: dict) -> NoteSummary:
    props = page.get("properties", {})
    return NoteSummary(
        note_id=page.get("id"),
        title=_extract_title(props.get("Nota", {})),
        category=_extract_select_name(props.get("Categoria", {})),
        tags=_extract_multi_select(props.get("Tags", {})),
        favorite=_extract_checkbox(props.get("Favorito", {})),
        url=page.get("url"),
    )


# ----------------- ENDPOINTS NOTAS -----------------

@app.post("/notion/notes", response_model=NoteSummary)
def create_note(body: CreateNoteRequest):
    """
    Cria uma nova nota na base 'Ideias & Notas Hub'.
    """
    database_id = _notes_db_or_500()

    try:
        props = build_note_properties(body)
        page = notion.pages.create(
            parent={"database_id": database_id},
            properties=props,
        )
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Erro ao criar nota no Notion: {e}",
        )

    return page_to_note_summary(page)


@app.get("/notion/notes", response_model=QueryNotesResponse)
def list_notes(
    favorite: Optional[bool] = Query(
        None,
        description="Se true, apenas notas marcadas como favoritas.",
    ),
    category: Optional[str] = Query(
        None,
        description="Filtra pela Categoria (select).",
    ),
):
    """
    Lista notas da base 'Ideias & Notas Hub'.
    """
    database_id = _notes_db_or_500()

    filters = []

    if favorite is not None:
        filters.append(
            {
                "property": "Favorito",
                "checkbox": {"equals": favorite},
            }
        )

    if category:
        filters.append(
            {
                "property": "Categoria",
                "select": {"equals": category},
            }
        )

    filter_obj = None
    if len(filters) == 1:
        filter_obj = filters[0]
    elif len(filters) > 1:
        filter_obj = {"and": filters}

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
            detail=f"Erro ao consultar notas: {e}",
        )

    notes = [page_to_note_summary(page) for page in result.get("results", [])]
    return QueryNotesResponse(notes=notes)


@app.patch("/notion/notes/{noteId}", response_model=UpdateNoteResponse)
def update_note(
    body: UpdateNoteRequest,
    noteId: str = Path(..., description="ID da nota na base Ideias & Notas Hub"),
):
    """
    Actualiza um registo na base Ideias & Notas Hub.
    """
    _notes_db_or_500()  # apenas valida que está configurado

    properties = {}

    if body.title is not None:
        properties["Nota"] = {
            "title": [{"text": {"content": body.title}}],
        }

    if body.category is not None:
        properties["Categoria"] = {"select": {"name": body.category}}

    if body.tags is not None:
        properties["Tags"] = {
            "multi_select": [{"name": tag} for tag in body.tags]
        }

    if body.context is not None:
        properties["Contexto"] = {
            "rich_text": [{"text": {"content": body.context}}]
        }

    if body.source is not None:
        properties["Fonte"] = {
            "rich_text": [{"text": {"content": body.source}}]
        }

    if body.favorite is not None:
        properties["Favorito"] = {"checkbox": body.favorite}

    if not properties:
        raise HTTPException(
            status_code=400,
            detail="Nenhum campo para actualizar.",
        )

    try:
        notion.pages.update(page_id=noteId, properties=properties)
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Erro ao actualizar nota no Notion: {e}",
        )

    return UpdateNoteResponse(
        note_id=noteId,
        updated_fields=list(properties.keys()),
    )
