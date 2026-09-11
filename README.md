# Backend — сервис обращений AI-поддержки Портала поставщиков

FastAPI + PostgreSQL. Хранит обращения (тикеты) пользователей чата, их статусы,
линию поддержки и историю изменений. Агентная логика живёт в ML-сервисе — здесь её нет.

## Стек

| Слой | Технология |
|---|---|
| API | FastAPI (Pydantic v2) |
| ORM | SQLAlchemy 2.0 (async) + asyncpg |
| БД | PostgreSQL 16 |
| Миграции | Alembic |
| Тесты | pytest + httpx + aiosqlite |

## Быстрый старт

### Docker (вся связка, миграции применяются автоматически)

```bash
docker compose up --build
# Swagger: http://localhost:8000/docs
```

### Локально

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install pytest pytest-asyncio httpx aiosqlite   # для тестов
cp .env.example .env                                 # поправить DATABASE_URL при необходимости

docker compose up -d db      # поднять только PostgreSQL
alembic upgrade head
uvicorn app.main:app --reload
```

### Тесты

```bash
pytest -q        # 9 тестов, идут на in-memory SQLite, PostgreSQL не нужен
```

## Модель данных

**tickets** — обращение:

| Поле | Тип | Назначение |
|---|---|---|
| `id` | UUID | PK |
| `thread_id` | str | ID диалога в ML-сервисе (LangGraph `thread_id`) |
| `user_id`, `channel` | str | Кто и откуда обратился |
| `subject`, `question` | str/text | Тема и текст обращения |
| `status` | enum | `created` / `in_progress` / `in_support` / `completed` |
| `support_line` | enum | `first` / `second` / `third`, null пока не классифицировано |
| `escalation_reason` | enum | `user_requested` / `agent_initiated` / `profanity` |
| `summary` | text | Саммари диалога для оператора при эскалации |
| `resolution`, `assignee` | text/str | Итог обработки и назначенный специалист |
| `metadata` | JSONB | Произвольные данные от ML (confidence, источники) |
| `escalated_at`, `closed_at`, `created_at`, `updated_at` | timestamptz | Отметки времени |

**ticket_events** — история: `from_status → to_status`, `actor`
(`user`/`agent`/`specialist`/`system`), `comment`, `created_at`. Пишется на каждую
смену статуса, удаляется каскадно вместе с тикетом.

### Переходы статусов

```
created ──▶ in_progress ──▶ in_support ──▶ completed
   │             │               ▲             (терминальный)
   │             └───────────────┘
   └──────────────▶ in_support / completed
```

`completed` — терминальный статус, любой переход из него отклоняется с **409**.
`in_support ⇄ in_progress` разрешены в обе стороны: оператор может вернуть
обращение агенту.

## Эндпоинты (`/api/v1`)

| Метод | Путь | Назначение |
|---|---|---|
| POST | `/tickets` | Создать обращение (вызывает фронт из чата) |
| GET | `/tickets` | Список с фильтрами `status`, `support_line`, `thread_id`, `user_id` + `limit`/`offset` |
| GET | `/tickets/{id}` | Обращение вместе с историей статусов |
| PATCH | `/tickets/{id}` | Обновить поля (линия поддержки, саммари, исполнитель, metadata) |
| POST | `/tickets/{id}/status` | Явная смена статуса с записью в историю |
| POST | `/tickets/{id}/escalate` | **Вызов сотрудника** → `in_support` + причина + саммари |
| GET | `/tickets/{id}/events` | История изменений |
| DELETE | `/tickets/{id}` | Удалить обращение |
| GET | `/health`, `/health/db` | Живость сервиса и доступность БД |

### Примеры

Создание обращения:

```bash
curl -X POST localhost:8000/api/v1/tickets -H 'Content-Type: application/json' -d '{
  "thread_id": "lg-thread-42",
  "user_id": "user-7",
  "question": "Как пройти аккредитацию на портале?",
  "metadata": {"confidence": 0.31}
}'
```

Вызов сотрудника:

```bash
curl -X POST localhost:8000/api/v1/tickets/<id>/escalate -H 'Content-Type: application/json' -d '{
  "reason": "agent_initiated",
  "support_line": "second",
  "summary": "Ответа в базе знаний нет, вопрос по аккредитации."
}'
```

Закрытие обращения оператором:

```bash
curl -X POST localhost:8000/api/v1/tickets/<id>/status -H 'Content-Type: application/json' -d '{
  "status": "completed", "actor": "specialist", "resolution": "Направлена инструкция"
}'
```

## Структура проекта

```
app/
  main.py              точка входа FastAPI
  core/                config (pydantic-settings), enums, HTTP-исключения
  db/                  declarative Base, async-движок и сессия
  models/ticket.py     Ticket, TicketEvent
  schemas/ticket.py    Pydantic-схемы запросов/ответов
  services/tickets.py  бизнес-логика (роутеры тонкие)
  api/v1/              роутеры: tickets, health
migrations/            Alembic
tests/                 pytest
```

## Что дальше

- Эндпоинт отзывов о специалистах (лайк/дизлайк + комментарий, привязка к `ticket_id`).
- Хранение логов диалогов для эвала и аналитики системных проблем.
- Прокси SSE-потока от ML-сервиса к фронтенду.
- Аутентификация — сейчас API открыт, `user_id` приходит от клиента как есть.
