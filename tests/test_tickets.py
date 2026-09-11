from httpx import AsyncClient

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


async def test_status_flow_to_completed_sets_closed_at(client: AsyncClient) -> None:
    ticket = await _create(client)
    await client.post(
        f"{API}/tickets/{ticket['id']}/status",
        json={"status": "in_progress", "actor": "agent"},
    )
    response = await client.post(
        f"{API}/tickets/{ticket['id']}/status",
        json={"status": "completed", "actor": "specialist", "resolution": "Вопрос решён"},
    )
    body = response.json()
    assert body["status"] == "completed"
    assert body["closed_at"] is not None
    assert body["resolution"] == "Вопрос решён"


async def test_completed_ticket_cannot_be_reopened(client: AsyncClient) -> None:
    ticket = await _create(client)
    await client.post(f"{API}/tickets/{ticket['id']}/status", json={"status": "completed"})
    response = await client.post(
        f"{API}/tickets/{ticket['id']}/status", json={"status": "in_progress"}
    )
    assert response.status_code == 409


async def test_escalation_of_completed_ticket_is_rejected(client: AsyncClient) -> None:
    ticket = await _create(client)
    await client.post(f"{API}/tickets/{ticket['id']}/status", json={"status": "completed"})
    response = await client.post(f"{API}/tickets/{ticket['id']}/escalate", json={})
    assert response.status_code == 409


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


async def test_unknown_ticket_returns_404(client: AsyncClient) -> None:
    response = await client.get(f"{API}/tickets/11111111-1111-1111-1111-111111111111")
    assert response.status_code == 404
