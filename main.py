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
    raise RuntimeError("NOTION_API_KEY tem de estar definido nas variáveis de ambiente.")

if NOTION_TASKS_DATABASE_ID is None:
    raise RuntimeError("NOTION_TASKS_DATABASE_ID tem de estar definido nas variáveis de ambiente.")

# Cliente oficial do Notion
notion = NotionClient(auth=NOTION_API_KEY)

app = FastAPI(title="Mia Notion API")


# ============================================================
#  HELPERS COMUNS
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


def _extract_multi_select_names(prop: dict) -> List[str]:
    ms = prop.get("multi_select")
    if not ms:
        return []
    return [x.get("name") for x in ms]


def _extract_date_start(prop: dict) -> Optional[str]:
    date_val = prop.get("date")
    if not date_val:
        return None
    return date_val.get("start")


def _extract_number(prop: dict) -> Optional[float]:
    return prop.get("number")


def _extract_checkbox(prop: dict) -> Optional[bool]:
    return prop.get("checkbox")


# ============================================================
#  TASK HUB (tarefas)
# ============================================================

class CreateNotionTaskRequest(BaseModel):
    task_title: str
    priority: Optional[str] = None            # Alta | Média | Baixa
    planned_date: Optional[str] = None        # YYYY-MM-DD
    deadline: Optional[str] = None            # YYYY-MM-DD
    duration: Optional[int] = None            # minutos
    energy_required: Optional[str] = None     # Alta | Média | Baixa
    area: Optional[str] = None                # Trabalho | Saúde | Pessoal | Família | Aprendizagem...
    notes: Optional[str] = None


class CreateNotionTaskResponse(BaseModel):
    task_id: str
    url: Optional[str]


class UpdateNotionTaskRequest(BaseModel):
    task_title: Optional[str] = None
    status: Optional[str] = None              # Inbox, Essencial, Leve, Delegável, Adiável, Concluída...
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


def build_notion_task_properties(body: CreateNotionTaskRequest):
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


@app.post("/notion/tasks", response_model=CreateNotionTaskResponse)
def create_notion_task(body: CreateNotionTaskRequest):
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
#  FILMES HUB
# ============================================================

def _movies_db_or_500() -> str:
    if not NOTION_MOVIES_DATABASE_ID:
        raise HTTPException(
            status_code=500,
            detail="NOTION_MOVIES_DATABASE_ID não está definido. "
                   "Configura o ID da base 'Filmes Hub' nas variáveis de ambiente.",
        )
    return NOTION_MOVIES_DATABASE_ID


class CreateMovieRequest(BaseModel):
    title: str
    watched: Optional[bool] = False
    category: Optional[str] = None
    notes: Optional[str] = None


class MovieSummary(BaseModel):
    movie_id: str
    title: Optional[str] = None
    watched: Optional[bool] = None
    category: Optional[str] = None
    url: Optional[str] = None


class QueryMoviesResponse(BaseModel):
    movies: List[MovieSummary]


class UpdateMovieRequest(BaseModel):
    title: Optional[str] = None
    watched: Optional[bool] = None
    category: Optional[str] = None
    notes: Optional[str] = None


class UpdateMovieResponse(BaseModel):
    movie_id: str
    updated_fields: List[str]


def build_movie_properties(body: CreateMovieRequest):
    props = {
        "Filme": {
            "title": [{"text": {"content": body.title}}],
        }
    }

    if body.category:
        props["Categoria"] = {"select": {"name": body.category}}

    if body.watched is not None:
        props["Já Vi"] = {"checkbox": body.watched}

    if body.notes:
        props["Notas"] = {"rich_text": [{"text": {"content": body.notes}}]}

    return props


def page_to_movie_summary(page: dict) -> MovieSummary:
    props = page.get("properties", {})
    return MovieSummary(
        movie_id=page.get("id"),
        title=_extract_title(props.get("Filme", {})),
        watched=_extract_checkbox(props.get("Já Vi", {})),
        category=_extract_select_name(props.get("Categoria", {})),
        url=page.get("url"),
    )


@app.post("/notion/movies", response_model=MovieSummary)
def create_movie(body: CreateMovieRequest):
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
        description="Filtra por 'Já Vi'. Se vazio, devolve todos.",
    )
):
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
            result = notion.databases.query(database_id=database_id)
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
    _movies_db_or_500()

    properties = {}

    if body.title is not None:
        properties["Filme"] = {"title": [{"text": {"content": body.title}}]}

    if body.category is not None:
        properties["Categoria"] = {"select": {"name": body.category}}

    if body.watched is not None:
        properties["Já Vi"] = {"checkbox": body.watched}

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
#  LIVROS HUB
# ============================================================

def _books_db_or_500() -> str:
    if not NOTION_BOOKS_DATABASE_ID:
        raise HTTPException(
            status_code=500,
            detail="NOTION_BOOKS_DATABASE_ID não está definido. "
                   "Configura o ID da base 'Livros Hub' nas variáveis de ambiente.",
        )
    return NOTION_BOOKS_DATABASE_ID


class CreateBookRequest(BaseModel):
    title: str
    author: Optional[str] = None
    status: Optional[str] = None          # Por ler | A ler | Lido
    favorite: Optional[bool] = None
    notes: Optional[str] = None


class BookSummary(BaseModel):
    book_id: str
    title: Optional[str] = None
    author: Optional[str] = None
    status: Optional[str] = None
    favorite: Optional[bool] = None
    url: Optional[str] = None


class QueryBooksResponse(BaseModel):
    books: List[BookSummary]


class UpdateBookRequest(BaseModel):
    title: Optional[str] = None
    author: Optional[str] = None
    status: Optional[str] = None
    favorite: Optional[bool] = None
    notes: Optional[str] = None


class UpdateBookResponse(BaseModel):
    book_id: str
    updated_fields: List[str]


def build_book_properties(body: CreateBookRequest):
    props = {
        "Título": {
            "title": [{"text": {"content": body.title}}],
        }
    }

    if body.author:
        props["Autor"] = {"rich_text": [{"text": {"content": body.author}}]}

    if body.status:
        props["Estado de leitura"] = {"select": {"name": body.status}}

    if body.favorite is not None:
        props["Favorito"] = {"checkbox": body.favorite}

    if body.notes:
        props["Notas"] = {"rich_text": [{"text": {"content": body.notes}}]}

    return props


def page_to_book_summary(page: dict) -> BookSummary:
    props = page.get("properties", {})
    return BookSummary(
        book_id=page.get("id"),
        title=_extract_title(props.get("Título", {})),
        author=_extract_rich_text(props.get("Autor", {})),
        status=_extract_select_name(props.get("Estado de leitura", {})),
        favorite=_extract_checkbox(props.get("Favorito", {})),
        url=page.get("url"),
    )


@app.post("/notion/books", response_model=BookSummary)
def create_book(body: CreateBookRequest):
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
        description="read=true → livros lidos; read=false → por ler; None → todos.",
    )
):
    database_id = _books_db_or_500()

    filter_obj = None
    if read is not None:
        if read:
            filter_obj = {
                "property": "Estado de leitura",
                "select": {"equals": "Lido"},
            }
        else:
            filter_obj = {
                "property": "Estado de leitura",
                "select": {"does_not_equal": "Lido"},
            }

    try:
        if filter_obj:
            result = notion.databases.query(
                database_id=database_id,
                filter=filter_obj,
            )
        else:
            result = notion.databases.query(database_id=database_id)
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
    _books_db_or_500()

    properties = {}

    if body.title is not None:
        properties["Título"] = {"title": [{"text": {"content": body.title}}]}

    if body.author is not None:
        properties["Autor"] = {"rich_text": [{"text": {"content": body.author}}]}

    if body.status is not None:
        properties["Estado de leitura"] = {"select": {"name": body.status}}

    if body.favorite is not None:
        properties["Favorito"] = {"checkbox": body.favorite}

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
#  FRASES & CITAÇÕES HUB
# ============================================================

def _quotes_db_or_500() -> str:
    if not NOTION_QUOTES_DATABASE_ID:
        raise HTTPException(
            status_code=500,
            detail="NOTION_QUOTES_DATABASE_ID não está definido. "
                   "Configura o ID da base de frases/citações nas variáveis de ambiente.",
        )
    return NOTION_QUOTES_DATABASE_ID


class CreateQuoteRequest(BaseModel):
    text: str
    author: Optional[str] = None
    source: Optional[str] = None
    category: Optional[str] = None
    favorite: Optional[bool] = None
    notes: Optional[str] = None


class QuoteSummary(BaseModel):
    quote_id: str
    text: Optional[str] = None
    author: Optional[str] = None
    category: Optional[str] = None
    favorite: Optional[bool] = None
    url: Optional[str] = None


class QueryQuotesResponse(BaseModel):
    quotes: List[QuoteSummary]


class UpdateQuoteRequest(BaseModel):
    text: Optional[str] = None
    author: Optional[str] = None
    source: Optional[str] = None
    category: Optional[str] = None
    favorite: Optional[bool] = None
    notes: Optional[str] = None


class UpdateQuoteResponse(BaseModel):
    quote_id: str
    updated_fields: List[str]


def build_quote_properties(body: CreateQuoteRequest):
    props = {
        "Texto": {
            "title": [{"text": {"content": body.text}}],
        }
    }

    if body.author:
        props["Autor"] = {"rich_text": [{"text": {"content": body.author}}]}

    if body.source:
        props["Fonte"] = {"rich_text": [{"text": {"content": body.source}}]}

    if body.category:
        props["Categoria"] = {"select": {"name": body.category}}

    if body.favorite is not None:
        props["Favorita"] = {"checkbox": body.favorite}

    if body.notes:
        props["Notas"] = {"rich_text": [{"text": {"content": body.notes}}]}

    return props


def page_to_quote_summary(page: dict) -> QuoteSummary:
    props = page.get("properties", {})
    return QuoteSummary(
        quote_id=page.get("id"),
        text=_extract_title(props.get("Texto", {})),
        author=_extract_rich_text(props.get("Autor", {})),
        category=_extract_select_name(props.get("Categoria", {})),
        favorite=_extract_checkbox(props.get("Favorita", {})),
        url=page.get("url"),
    )


@app.post("/notion/quotes", response_model=QuoteSummary)
def create_quote(body: CreateQuoteRequest):
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
        description="Filtra por autor. Se vazio, devolve todas.",
    ),
    favorite: Optional[bool] = Query(
        None,
        description="Filtra por favoritas.",
    ),
):
    database_id = _quotes_db_or_500()

    filters = []

    if author:
        filters.append({
            "property": "Autor",
            "rich_text": {"contains": author},
        })

    if favorite is not None:
        filters.append({
            "property": "Favorita",
            "checkbox": {"equals": favorite},
        })

    filter_obj = None
    if filters:
        if len(filters) == 1:
            filter_obj = filters[0]
        else:
            filter_obj = {"and": filters}

    try:
        if filter_obj:
            result = notion.databases.query(
                database_id=database_id,
                filter=filter_obj,
            )
        else:
            result = notion.databases.query(database_id=database_id)
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
    quoteId: str = Path(..., description="ID da frase na base de Citações"),
):
    _quotes_db_or_500()

    properties = {}

    if body.text is not None:
        properties["Texto"] = {"title": [{"text": {"content": body.text}}]}

    if body.author is not None:
        properties["Autor"] = {"rich_text": [{"text": {"content": body.author}}]}

    if body.source is not None:
        properties["Fonte"] = {"rich_text": [{"text": {"content": body.source}}]}

    if body.category is not None:
        properties["Categoria"] = {"select": {"name": body.category}}

    if body.favorite is not None:
        properties["Favorita"] = {"checkbox": body.favorite}

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
#  IDEIAS & NOTAS HUB
# ============================================================

def _notes_db_or_500() -> str:
    if not NOTION_NOTES_DATABASE_ID:
        raise HTTPException(
            status_code=500,
            detail="NOTION_NOTES_DATABASE_ID não está definido. "
                   "Configura o ID da base 'Ideias & Notas Hub' nas variáveis de ambiente.",
        )
    return NOTION_NOTES_DATABASE_ID


class CreateNoteRequest(BaseModel):
    title: str
    category: Optional[str] = None
    emotional_energy: Optional[str] = None   # Alta, Média, Baixa...
    impact: Optional[str] = None             # por ex.: Alto, Médio, Baixo
    favorite: Optional[bool] = None
    date: Optional[str] = None               # YYYY-MM-DD
    details: Optional[str] = None            # campo "Notas detalhadas"


class NoteSummary(BaseModel):
    note_id: str
    title: Optional[str] = None
    category: Optional[str] = None
    emotional_energy: Optional[str] = None
    impact: Optional[str] = None
    favorite: Optional[bool] = None
    date: Optional[str] = None
    url: Optional[str] = None


class QueryNotesResponse(BaseModel):
    notes: List[NoteSummary]


class UpdateNoteRequest(BaseModel):
    title: Optional[str] = None
    category: Optional[str] = None
    emotional_energy: Optional[str] = None
    impact: Optional[str] = None
    favorite: Optional[bool] = None
    date: Optional[str] = None
    details: Optional[str] = None


class UpdateNoteResponse(BaseModel):
    note_id: str
    updated_fields: List[str]


def build_note_properties(body: CreateNoteRequest):
    props = {
        "Título / Nota": {
            "title": [{"text": {"content": body.title}}],
        }
    }

    if body.category:
        props["Categoria"] = {"select": {"name": body.category}}

    if body.emotional_energy:
        props["Energia emocional"] = {"select": {"name": body.emotional_energy}}

    if body.impact:
        props["Impacto"] = {"select": {"name": body.impact}}

    if body.favorite is not None:
        props["Favorito"] = {"checkbox": body.favorite}

    if body.date:
        props["Data"] = {"date": {"start": body.date}}

    if body.details:
        props["Notas detalhadas"] = {
            "rich_text": [{"text": {"content": body.details}}]
        }

    return props


def page_to_note_summary(page: dict) -> NoteSummary:
    props = page.get("properties", {})
    return NoteSummary(
        note_id=page.get("id"),
        title=_extract_title(props.get("Título / Nota", {})),
        category=_extract_select_name(props.get("Categoria", {})),
        emotional_energy=_extract_select_name(props.get("Energia emocional", {})),
        impact=_extract_select_name(props.get("Impacto", {})),
        favorite=_extract_checkbox(props.get("Favorito", {})),
        date=_extract_date_start(props.get("Data", {})),
        url=page.get("url"),
    )


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
        description="Filtra por favorito.",
    ),
    category: Optional[str] = Query(
        None,
        description="Filtra por categoria.",
    ),
):
    """
    Lista notas da base 'Ideias & Notas Hub'.
    """
    database_id = _notes_db_or_500()

    filters = []

    if favorite is not None:
        filters.append({
            "property": "Favorito",
            "checkbox": {"equals": favorite},
        })

    if category:
        filters.append({
            "property": "Categoria",
            "select": {"equals": category},
        })

    filter_obj = None
    if filters:
        if len(filters) == 1:
            filter_obj = filters[0]
        else:
            filter_obj = {"and": filters}

    try:
        if filter_obj:
            result = notion.databases.query(
                database_id=database_id,
                filter=filter_obj,
            )
        else:
            result = notion.databases.query(database_id=database_id)
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
    _notes_db_or_500()

    properties = {}

    if body.title is not None:
        properties["Título / Nota"] = {
            "title": [{"text": {"content": body.title}}]
        }

    if body.category is not None:
        properties["Categoria"] = {"select": {"name": body.category}}

    if body.emotional_energy is not None:
        properties["Energia emocional"] = {
            "select": {"name": body.emotional_energy}
        }

    if body.impact is not None:
        properties["Impacto"] = {"select": {"name": body.impact}}

    if body.favorite is not None:
        properties["Favorito"] = {"checkbox": body.favorite}

    if body.date is not None:
        properties["Data"] = {"date": {"start": body.date}}

    if body.details is not None:
        properties["Notas detalhadas"] = {
            "rich_text": [{"text": {"content": body.details}}]
        }

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


# ============================================================
#  INVESTIMENTOS HUB
# ============================================================

def _investments_db_or_500() -> str:
    if not NOTION_INVESTMENTS_DATABASE_ID:
        raise HTTPException(
            status_code=500,
            detail="NOTION_INVESTMENTS_DATABASE_ID não está definido. "
                   "Configura o ID da base 'Investimentos Hub' nas variáveis de ambiente.",
        )
    return NOTION_INVESTMENTS_DATABASE_ID


class CreateInvestmentRequest(BaseModel):
    asset: str                      # Ativo
    quantity: float                 # Quantidade
    average_price_usd: float        # Preço Médio (USD)
    last_price_usd: Optional[float] = None           # Último Preço Capturado (USD)
    aportes_totais_usd: Optional[float] = None       # Aportes Totais (USD)
    saldo_atual_usd: Optional[float] = None          # Saldo Atual (USD)
    lucro_usd: Optional[float] = None                # Lucro (USD)
    percent_lucro: Optional[float] = None            # % Lucro
    tipo_ativo: Optional[str] = None                 # Tipo de Ativo (select)


class InvestmentSummary(BaseModel):
    investment_id: str
    asset: Optional[str] = None
    quantity: Optional[float] = None
    average_price_usd: Optional[float] = None
    last_price_usd: Optional[float] = None
    aportes_totais_usd: Optional[float] = None
    saldo_atual_usd: Optional[float] = None
    lucro_usd: Optional[float] = None
    percent_lucro: Optional[float] = None
    tipo_ativo: Optional[str] = None
    url: Optional[str] = None


class QueryInvestmentsResponse(BaseModel):
    investments: List[InvestmentSummary]


class UpdateInvestmentRequest(BaseModel):
    asset: Optional[str] = None
    quantity: Optional[float] = None
    average_price_usd: Optional[float] = None
    last_price_usd: Optional[float] = None
    aportes_totais_usd: Optional[float] = None
    saldo_atual_usd: Optional[float] = None
    lucro_usd: Optional[float] = None
    percent_lucro: Optional[float] = None
    tipo_ativo: Optional[str] = None


class UpdateInvestmentResponse(BaseModel):
    investment_id: str
    updated_fields: List[str]


def build_investment_properties_from_create(body: CreateInvestmentRequest):
    """
    Mapeia diretamente os campos do pedido para as colunas da base Investimentos Hub.
    A Mia é responsável por calcular lucro/%lucro antes de enviar, se quiser.
    """
    props = {
        "Ativo": {
            "title": [{"text": {"content": body.asset}}],
        },
        "Quantidade": {"number": body.quantity},
        "Preço Médio (USD)": {"number": body.average_price_usd},
    }

    if body.last_price_usd is not None:
        props["Último Preço Capturado (USD)"] = {"number": body.last_price_usd}

    if body.aportes_totais_usd is not None:
        props["Aportes Totais (USD)"] = {"number": body.aportes_totais_usd}

    if body.saldo_atual_usd is not None:
        props["Saldo Atual (USD)"] = {"number": body.saldo_atual_usd}

    if body.lucro_usd is not None:
        props["Lucro (USD)"] = {"number": body.lucro_usd}

    if body.percent_lucro is not None:
        props["% Lucro"] = {"number": body.percent_lucro}

    if body.tipo_ativo is not None:
        props["Tipo de Ativo"] = {"select": {"name": body.tipo_ativo}}

    return props


def build_investment_properties_from_update(body: UpdateInvestmentRequest):
    """
    Só escreve os campos enviados; não recalcula nada.
    A Mia faz as contas e envia os valores certos.
    """
    props = {}

    if body.asset is not None:
        props["Ativo"] = {"title": [{"text": {"content": body.asset}}]}

    if body.quantity is not None:
        props["Quantidade"] = {"number": body.quantity}

    if body.average_price_usd is not None:
        props["Preço Médio (USD)"] = {"number": body.average_price_usd}

    if body.last_price_usd is not None:
        props["Último Preço Capturado (USD)"] = {"number": body.last_price_usd}

    if body.aportes_totais_usd is not None:
        props["Aportes Totais (USD)"] = {"number": body.aportes_totais_usd}

    if body.saldo_atual_usd is not None:
        props["Saldo Atual (USD)"] = {"number": body.saldo_atual_usd}

    if body.lucro_usd is not None:
        props["Lucro (USD)"] = {"number": body.lucro_usd}

    if body.percent_lucro is not None:
        props["% Lucro"] = {"number": body.percent_lucro}

    if body.tipo_ativo is not None:
        props["Tipo de Ativo"] = {"select": {"name": body.tipo_ativo}}

    return props


def page_to_investment_summary(page: dict) -> InvestmentSummary:
    props = page.get("properties", {})
    return InvestmentSummary(
        investment_id=page.get("id"),
        asset=_extract_title(props.get("Ativo", {})),
        quantity=_extract_number(props.get("Quantidade", {})),
        average_price_usd=_extract_number(props.get("Preço Médio (USD)", {})),
        last_price_usd=_extract_number(props.get("Último Preço Capturado (USD)", {})),
        aportes_totais_usd=_extract_number(props.get("Aportes Totais (USD)", {})),
        saldo_atual_usd=_extract_number(props.get("Saldo Atual (USD)", {})),
        lucro_usd=_extract_number(props.get("Lucro (USD)", {})),
        percent_lucro=_extract_number(props.get("% Lucro", {})),
        tipo_ativo=_extract_select_name(props.get("Tipo de Ativo", {})),
        url=page.get("url"),
    )


@app.post("/notion/investments", response_model=InvestmentSummary)
def create_investment(body: CreateInvestmentRequest):
    database_id = _investments_db_or_500()

    try:
        props = build_investment_properties_from_create(body)
        page = notion.pages.create(
            parent={"database_id": database_id},
            properties=props,
        )
        return page_to_investment_summary(page)
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Erro ao criar investimento no Notion: {e}",
        )


@app.get("/notion/investments", response_model=QueryInvestmentsResponse)
def list_investments(
    asset: Optional[str] = Query(
        None, description="Filtra por nome do ativo (campo 'Ativo' contém este texto)."
    ),
    only_profitable: Optional[bool] = Query(
        None, description="true → Lucro (USD) > 0; false → Lucro (USD) < 0; None → todos."
    ),
):
    database_id = _investments_db_or_500()

    filters = []

    if asset:
        filters.append({
            "property": "Ativo",
            "title": {"contains": asset},
        })

    if only_profitable is True:
        filters.append({
            "property": "Lucro (USD)",
            "number": {"greater_than": 0},
        })
    elif only_profitable is False:
        filters.append({
            "property": "Lucro (USD)",
            "number": {"less_than": 0},
        })

    if filters:
        if len(filters) == 1:
            filter_obj = filters[0]
        else:
            filter_obj = {"and": filters}
    else:
        filter_obj = None

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
            detail=f"Erro ao consultar investimentos: {e}",
        )

    investments = [page_to_investment_summary(page) for page in result.get("results", [])]
    return QueryInvestmentsResponse(investments=investments)


@app.patch("/notion/investments/{investmentId}", response_model=UpdateInvestmentResponse)
def update_investment(
    body: UpdateInvestmentRequest,
    investmentId: str = Path(..., description="ID do investimento na base Investimentos Hub"),
):
    _investments_db_or_500()

    properties = build_investment_properties_from_update(body)

    if not properties:
        raise HTTPException(
            status_code=400,
            detail="Nenhum campo para actualizar.",
        )

    try:
        notion.pages.update(page_id=investmentId, properties=properties)
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Erro ao actualizar investimento no Notion: {e}",
        )

    return UpdateInvestmentResponse(
        investment_id=investmentId,
        updated_fields=list(properties.keys()),
    )
