import uuid

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.training_example import TrainingExample

API = "/api/v1"


async def _create(client: AsyncClient, **overrides) -> dict:
    payload = {
        "thread_id": "thread-1",
        "question": "Как пройти аккредитацию на портале?",
        "user_id": "user-42",
        "metadata": {"confidence": 0.31},
    } | overrides
    response = await client.post(f"{API}/tickets", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


async def test_create_ticket_starts_in_created_status(client: AsyncClient) -> None:
    ticket = await _create(client)
    assert ticket["status"] == "created"
    assert ticket["support_line"] is None
    assert ticket["metadata"] == {"confidence": 0.31}


async def test_create_ticket_writes_history_event(client: AsyncClient) -> None:
    ticket = await _create(client)
    response = await client.get(f"{API}/tickets/{ticket['id']}/events")
    events = response.json()
    assert len(events) == 1
    assert events[0]["to_status"] == "created"
    assert events[0]["from_status"] is None


async def test_escalate_moves_ticket_to_support(client: AsyncClient) -> None:
    ticket = await _create(client)
    response = await client.post(
        f"{API}/tickets/{ticket['id']}/escalate",
        json={
            "reason": "agent_initiated",
            "support_line": "second",
            "summary": "Пользователь спрашивал про аккредитацию, ответа в БЗ нет.",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "in_support"
    assert body["support_line"] == "second"
    assert body["escalation_reason"] == "agent_initiated"
    assert body["escalated_at"] is not None


async def test_status_flow_to_closed_sets_closed_at(client: AsyncClient) -> None:
    ticket = await _create(client)
    await client.post(
        f"{API}/tickets/{ticket['id']}/status",
        json={"status": "in_progress", "actor": "agent"},
    )
    response = await client.post(
        f"{API}/tickets/{ticket['id']}/status",
        json={"status": "closed", "actor": "specialist", "resolution": "Вопрос решён"},
    )
    body = response.json()
    assert body["status"] == "closed"
    assert body["closed_at"] is not None
    assert body["resolution"] == "Вопрос решён"


async def test_close_endpoint_closes_ticket_and_writes_event(client: AsyncClient) -> None:
    ticket = await _create(client)
    response = await client.post(
        f"{API}/tickets/{ticket['id']}/close",
        json={"actor": "user", "resolution": "Пользователь закрыл обращение"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "closed"
    assert body["closed_at"] is not None
    assert body["feedback"] is None

    events = (await client.get(f"{API}/tickets/{ticket['id']}/events")).json()
    assert events[-1]["to_status"] == "closed"
    assert events[-1]["actor"] == "user"


async def test_close_stores_transcript(client: AsyncClient) -> None:
    ticket = await _create(client)
    transcript = "Пользователь: вопрос\n\nАгент: ответ"
    response = await client.post(
        f"{API}/tickets/{ticket['id']}/close",
        json={"actor": "user", "transcript": transcript},
    )
    assert response.status_code == 200
    assert response.json()["transcript"] == transcript

    fetched = (await client.get(f"{API}/tickets/{ticket['id']}")).json()
    assert fetched["transcript"] == transcript


async def test_double_close_without_transcript_keeps_previous(client: AsyncClient) -> None:
    ticket = await _create(client)
    transcript = "Пользователь: вопрос\n\nАгент: ответ"
    await client.post(
        f"{API}/tickets/{ticket['id']}/close",
        json={"actor": "user", "transcript": transcript},
    )
    second = await client.post(f"{API}/tickets/{ticket['id']}/close", json={})
    assert second.json()["transcript"] == transcript


async def test_closed_ticket_cannot_be_reopened(client: AsyncClient) -> None:
    ticket = await _create(client)
    await client.post(f"{API}/tickets/{ticket['id']}/close", json={})
    response = await client.post(
        f"{API}/tickets/{ticket['id']}/status", json={"status": "in_progress"}
    )
    assert response.status_code == 409


async def test_double_close_is_idempotent(client: AsyncClient) -> None:
    ticket = await _create(client)
    first = await client.post(f"{API}/tickets/{ticket['id']}/close", json={})
    second = await client.post(f"{API}/tickets/{ticket['id']}/close", json={})
    assert second.status_code == 200
    assert second.json()["closed_at"] == first.json()["closed_at"]

    events = (await client.get(f"{API}/tickets/{ticket['id']}/events")).json()
    assert [event["to_status"] for event in events] == ["created", "closed"]


async def test_escalation_of_closed_ticket_is_rejected(client: AsyncClient) -> None:
    ticket = await _create(client)
    await client.post(f"{API}/tickets/{ticket['id']}/close", json={})
    response = await client.post(f"{API}/tickets/{ticket['id']}/escalate", json={})
    assert response.status_code == 409


async def test_feedback_after_close(client: AsyncClient) -> None:
    ticket = await _create(client)
    await client.post(f"{API}/tickets/{ticket['id']}/close", json={})

    response = await client.post(
        f"{API}/tickets/{ticket['id']}/feedback",
        json={"score": 5, "comment": "Быстро помогли"},
    )
    assert response.status_code == 201
    assert response.json()["score"] == 5

    ticket_body = (await client.get(f"{API}/tickets/{ticket['id']}")).json()
    assert ticket_body["feedback"]["score"] == 5
    assert ticket_body["feedback"]["comment"] == "Быстро помогли"


async def test_feedback_saves_training_example(client: AsyncClient, session: AsyncSession) -> None:
    ticket = await _create(client)
    await client.post(f"{API}/tickets/{ticket['id']}/close", json={})

    response = await client.post(
        f"{API}/tickets/{ticket['id']}/feedback",
        json={
            "score": 5,
            "comment": "Быстро помогли",
            "summary": "Пользователь не мог пройти аккредитацию, помогли с ЭП",
            "transcript": "Пользователь: вопрос\n\nАгент: ответ",
        },
    )
    assert response.status_code == 201, response.text

    example = await session.scalar(
        select(TrainingExample).where(TrainingExample.ticket_id == uuid.UUID(ticket["id"]))
    )
    assert example is not None
    assert example.question == ticket["question"]
    assert example.score == 5
    assert example.summary == "Пользователь не мог пройти аккредитацию, помогли с ЭП"
    assert example.transcript == "Пользователь: вопрос\n\nАгент: ответ"


async def test_rerating_updates_same_training_example(
    client: AsyncClient, session: AsyncSession
) -> None:
    ticket = await _create(client)
    await client.post(f"{API}/tickets/{ticket['id']}/close", json={})

    await client.post(
        f"{API}/tickets/{ticket['id']}/feedback",
        json={"score": 2, "summary": "первая версия", "transcript": "…"},
    )
    await client.post(
        f"{API}/tickets/{ticket['id']}/feedback",
        json={"score": 5, "summary": "вторая версия", "transcript": "…"},
    )

    result = await session.scalars(
        select(TrainingExample).where(TrainingExample.ticket_id == uuid.UUID(ticket["id"]))
    )
    examples = result.all()
    assert len(examples) == 1
    assert examples[0].score == 5
    assert examples[0].summary == "вторая версия"


async def test_feedback_before_close_is_rejected(client: AsyncClient) -> None:
    ticket = await _create(client)
    response = await client.post(f"{API}/tickets/{ticket['id']}/feedback", json={"score": 4})
    assert response.status_code == 409


async def test_feedback_score_out_of_range_is_rejected(client: AsyncClient) -> None:
    ticket = await _create(client)
    await client.post(f"{API}/tickets/{ticket['id']}/close", json={})
    for score in (0, 6):
        response = await client.post(
            f"{API}/tickets/{ticket['id']}/feedback", json={"score": score}
        )
        assert response.status_code == 422


async def test_repeated_feedback_overwrites_previous(client: AsyncClient) -> None:
    ticket = await _create(client)
    await client.post(f"{API}/tickets/{ticket['id']}/close", json={})
    await client.post(f"{API}/tickets/{ticket['id']}/feedback", json={"score": 2})
    await client.post(
        f"{API}/tickets/{ticket['id']}/feedback", json={"score": 4, "comment": "Передумал"}
    )

    response = await client.get(f"{API}/tickets/{ticket['id']}/feedback")
    body = response.json()
    assert body["score"] == 4
    assert body["comment"] == "Передумал"


async def test_feedback_missing_returns_404(client: AsyncClient) -> None:
    ticket = await _create(client)
    await client.post(f"{API}/tickets/{ticket['id']}/close", json={})
    response = await client.get(f"{API}/tickets/{ticket['id']}/feedback")
    assert response.status_code == 404


async def test_list_filters_by_status_and_line(client: AsyncClient) -> None:
    first = await _create(client, thread_id="t-1")
    await _create(client, thread_id="t-2")
    await client.post(
        f"{API}/tickets/{first['id']}/escalate",
        json={"reason": "user_requested", "support_line": "third"},
    )

    response = await client.get(f"{API}/tickets", params={"status": "in_support"})
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["support_line"] == "third"

    by_thread = await client.get(f"{API}/tickets", params={"thread_id": "t-2"})
    assert by_thread.json()["total"] == 1


async def test_patch_updates_support_line(client: AsyncClient) -> None:
    ticket = await _create(client)
    response = await client.patch(
        f"{API}/tickets/{ticket['id']}", json={"support_line": "first", "assignee": "operator-7"}
    )
    body = response.json()
    assert body["support_line"] == "first"
    assert body["assignee"] == "operator-7"


async def test_list_scoped_by_user_id(client: AsyncClient) -> None:
    """Фронт передаёт `user_id` сессии браузера и по нему получает историю обращений."""
    await _create(client, thread_id="s1-a", user_id="session-1")
    await _create(client, thread_id="s1-b", user_id="session-1")
    await _create(client, thread_id="s2-a", user_id="session-2")

    response = await client.get(f"{API}/tickets", params={"user_id": "session-1"})
    assert response.json()["total"] == 2


async def test_sort_by_status_priority(client: AsyncClient) -> None:
    """Ждущие человека — наверху, закрытые — в конце.

    По два обращения на статус: при сломанной сортировке (одинаковый вес у всех)
    порядок определялся бы временем создания, и такая раскладка не сложилась бы.
    """
    for index in range(2):
        waiting = await _create(client, thread_id=f"w-{index}", user_id="s")
        await client.post(f"{API}/tickets/{waiting['id']}/escalate", json={})

        answering = await _create(client, thread_id=f"a-{index}", user_id="s")
        await client.post(
            f"{API}/tickets/{answering['id']}/status",
            json={"status": "in_progress", "actor": "agent"},
        )

        await _create(client, thread_id=f"f-{index}", user_id="s")

        done = await _create(client, thread_id=f"c-{index}", user_id="s")
        await client.post(f"{API}/tickets/{done['id']}/close", json={})

    response = await client.get(
        f"{API}/tickets", params={"user_id": "s", "sort": "status_priority"}
    )
    statuses = [item["status"] for item in response.json()["items"]]
    assert statuses == [
        "in_support",
        "in_support",
        "in_progress",
        "in_progress",
        "created",
        "created",
        "closed",
        "closed",
    ]


async def test_pagination_does_not_repeat_tickets(client: AsyncClient) -> None:
    """Порядок устойчив: страницы не пересекаются даже при одинаковом created_at."""
    for index in range(6):
        await _create(client, thread_id=f"page-{index}", user_id="pager")

    first_page = await client.get(
        f"{API}/tickets", params={"user_id": "pager", "limit": 3, "offset": 0}
    )
    second_page = await client.get(
        f"{API}/tickets", params={"user_id": "pager", "limit": 3, "offset": 3}
    )
    ids = [item["id"] for item in first_page.json()["items"]] + [
        item["id"] for item in second_page.json()["items"]
    ]
    assert len(set(ids)) == 6


async def test_new_dialog_does_not_touch_previous_tickets(client: AsyncClient) -> None:
    """«Новое обращение» на фронте заводит новый тикет, старые остаются в базе как есть."""
    old = await _create(client, thread_id="old-thread", user_id="same-session")
    await client.post(f"{API}/tickets/{old['id']}/escalate", json={})

    await _create(client, thread_id="new-thread", user_id="same-session")

    history = (await client.get(f"{API}/tickets", params={"user_id": "same-session"})).json()
    assert history["total"] == 2
    kept = next(item for item in history["items"] if item["id"] == old["id"])
    assert kept["status"] == "in_support"


async def test_unknown_ticket_returns_404(client: AsyncClient) -> None:
    response = await client.get(f"{API}/tickets/11111111-1111-1111-1111-111111111111")
    assert response.status_code == 404
