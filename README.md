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
cp .env.example .env      # при необходимости поправить POSTGRES_* и CORS_ORIGINS
docker compose up --build
# Swagger: http://localhost:8000/docs
```

API и PostgreSQL публикуются только на `127.0.0.1` — наружу локальная связка не смотрит.

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
pytest -q        # 16 тестов, идут на in-memory SQLite, PostgreSQL не нужен
```

## Модель данных

**tickets** — обращение:

| Поле | Тип | Назначение |
|---|---|---|
| `id` | UUID | PK |
| `thread_id` | str | ID диалога в ML-сервисе (LangGraph `thread_id`) |
| `user_id`, `channel` | str | Кто и откуда обратился |
| `subject`, `question` | str/text | Тема и текст обращения |
| `status` | enum | `created` / `in_progress` / `in_support` / `closed` |
| `support_line` | enum | `first` / `second` / `third`, null пока не классифицировано |
| `escalation_reason` | enum | `user_requested` / `agent_initiated` / `profanity` |
| `summary` | text | Саммари диалога для оператора при эскалации |
| `resolution`, `assignee` | text/str | Итог обработки и назначенный специалист |
| `metadata` | JSONB | Произвольные данные от ML (confidence, источники) |
| `escalated_at`, `closed_at`, `created_at`, `updated_at` | timestamptz | Отметки времени |

**ticket_events** — история: `from_status → to_status`, `actor`
(`user`/`agent`/`specialist`/`system`), `comment`, `created_at`. Пишется на каждую
смену статуса, удаляется каскадно вместе с тикетом.

**ticket_feedback** — оценка обращения: `score` (1–5, CHECK в БД), `comment`,
`created_at`, `updated_at`. Одна оценка на обращение (`ticket_id` UNIQUE),
удаляется каскадно вместе с тикетом.

### Переходы статусов

```
created ──▶ in_progress ──▶ in_support ──▶ closed
   │             │               ▲          (терминальный)
   │             └───────────────┘
   └──────────────▶ in_support / closed
```

`closed` — терминальный статус, любой переход из него отклоняется с **409**.
`in_support ⇄ in_progress` разрешены в обе стороны: оператор может вернуть
обращение агенту. Повторное закрытие уже закрытого обращения возвращает 200,
не меняет `closed_at` и не плодит записи в истории.

## Эндпоинты (`/api/v1`)

| Метод | Путь | Назначение |
|---|---|---|
| POST | `/tickets` | Создать обращение (вызывает фронт из чата) |
| GET | `/tickets` | Список с фильтрами `status`, `support_line`, `thread_id`, `user_id` + `limit`/`offset` |
| GET | `/tickets/{id}` | Обращение вместе с историей статусов |
| PATCH | `/tickets/{id}` | Обновить поля (линия поддержки, саммари, исполнитель, metadata) |
| POST | `/tickets/{id}/status` | Явная смена статуса с записью в историю |
| POST | `/tickets/{id}/escalate` | **Вызов сотрудника** → `in_support` + причина + саммари |
| POST | `/tickets/{id}/close` | **Закрыть обращение** → `closed`; после этого фронт показывает форму оценки |
| POST | `/tickets/{id}/feedback` | **Оценка 1–5 звёзд + комментарий**; только для закрытого обращения, иначе 409 |
| GET | `/tickets/{id}/feedback` | Оценка обращения (404, если ещё не оценено) |
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

Закрытие обращения:

```bash
curl -X POST localhost:8000/api/v1/tickets/<id>/close -H 'Content-Type: application/json' -d '{
  "actor": "user", "resolution": "Направлена инструкция"
}'
```

Оценка после закрытия (форма со звёздами на фронте):

```bash
curl -X POST localhost:8000/api/v1/tickets/<id>/feedback -H 'Content-Type: application/json' -d '{
  "score": 5, "comment": "Быстро помогли"
}'
```

## Деплой на прод (ked-ai.site)

```bash
# на сервере
cp .env.example .env
# обязательно задать длинный случайный POSTGRES_PASSWORD
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

Что делает продовый оверлей:

- `api` слушает только `127.0.0.1:8000` — наружу смотрит системный **nginx**
  (порты 80/443); `db` порт не публикует вообще — до неё ходит исключительно `api`
  по внутренней сети compose;
- TLS-сертификат Let's Encrypt выпускает и продлевает **certbot**, запущенный на хосте
  (не в docker), через `certbot --nginx`;
- `POSTGRES_PASSWORD` обязателен — без него compose не стартует, дефолта в проде нет;
- `DEBUG=false`, `ENVIRONMENT=production`, `CORS_ORIGINS=https://ked-ai.site`.

Маршрутизация на домене (см. [deploy/nginx.conf](deploy/nginx.conf)): `/backend/api/v1/*`
проксируется в backend (`127.0.0.1:8000/api/v1/*`), `/ml` зарезервирован под ML-сервис
(пока отвечает заглушкой 503), корень — под фронтенд.

**Предусловия на сервере:** A-запись `ked-ai.site` → IP сервера, установлены `nginx` и
`certbot` (`apt install nginx certbot python3-certbot-nginx`), открытые порты 80 и 443
(без 80 не пройдёт HTTP-01 проверка Let's Encrypt).

**Чего пока нет:** аутентификации API, бэкапов БД, ограничения скорости запросов.
`/docs` наружу не проксируется в `deploy/nginx.conf` — Swagger на проде недоступен снаружи.

## Структура проекта

```
app/
  main.py              точка входа FastAPI
  core/                config (pydantic-settings), enums, HTTP-исключения
  db/                  declarative Base, async-движок и сессия
  models/ticket.py     Ticket, TicketEvent, TicketFeedback
  schemas/ticket.py    Pydantic-схемы запросов/ответов
  services/tickets.py  бизнес-логика (роутеры тонкие)
  api/v1/              роутеры: tickets, health
migrations/            Alembic
deploy/nginx.conf      reverse proxy для прода (TLS через certbot)
tests/                 pytest
```

## Что дальше

- Агрегаты по оценкам (средний балл по линиям поддержки) для аналитики системных проблем.
- Хранение логов диалогов для эвала и аналитики системных проблем.
- Прокси SSE-потока от ML-сервиса к фронтенду.
- Аутентификация — сейчас API открыт, `user_id` приходит от клиента как есть.
