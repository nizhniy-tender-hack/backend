from httpx import AsyncClient

API = "/api/v1"


async def _create(client: AsyncClient, **overrides) -> dict:
    payload = {
        "thread_id": "thread-analytics",
        "question": "Как пройти аккредитацию на портале?",
        "user_id": "user-42",
    } | overrides
    response = await client.post(f"{API}/tickets", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


async def _close(client: AsyncClient, ticket_id: str, score: int | None = None) -> None:
    response = await client.post(f"{API}/tickets/{ticket_id}/close", json={"actor": "user"})
    assert response.status_code == 200, response.text
    if score is not None:
        rated = await client.post(f"{API}/tickets/{ticket_id}/feedback", json={"score": score})
        assert rated.status_code == 201, rated.text


async def _overview(client: AsyncClient) -> dict:
    response = await client.get(f"{API}/analytics/overview")
    assert response.status_code == 200, response.text
    return response.json()


async def test_overview_on_empty_database(client: AsyncClient) -> None:
    body = await _overview(client)
    assert body["totals"]["total"] == 0
    assert body["resolution"]["ml_resolution_rate"] == 0.0
    assert body["ratings"]["overall"]["average"] is None
    assert body["by_support_line"] == []


async def test_ml_closed_and_escalated_are_counted_apart(client: AsyncClient) -> None:
    by_ml = await _create(client, support_line="first")
    await _close(client, by_ml["id"], score=5)

    escalated_closed = await _create(client, support_line="second")
    await client.post(
        f"{API}/tickets/{escalated_closed['id']}/escalate", json={"reason": "agent_initiated"}
    )
    await _close(client, escalated_closed["id"], score=2)

    still_in_support = await _create(client)
    await client.post(
        f"{API}/tickets/{still_in_support['id']}/escalate", json={"reason": "user_requested"}
    )

    body = await _overview(client)
    resolution = body["resolution"]
    assert resolution["closed_total"] == 2
    assert resolution["closed_by_ml"] == 1
    assert resolution["closed_after_escalation"] == 1
    assert resolution["escalated_total"] == 2
    assert resolution["escalated_open"] == 1
    # Обработано три обращения (2 закрытых + 1 у поддержки), ML закрыла одно.
    assert resolution["ml_resolution_rate"] == round(1 / 3, 4)

    reasons = {item["reason"]: item["count"] for item in body["by_escalation_reason"]}
    assert reasons == {"user_requested": 1, "agent_initiated": 1}


async def test_ratings_split_by_who_resolved(client: AsyncClient) -> None:
    by_ml = await _create(client)
    await _close(client, by_ml["id"], score=5)

    escalated = await _create(client)
    await client.post(f"{API}/tickets/{escalated['id']}/escalate", json={"reason": "profanity"})
    await _close(client, escalated["id"], score=3)

    ratings = (await _overview(client))["ratings"]
    assert ratings["overall"]["count"] == 2
    assert ratings["overall"]["average"] == 4.0
    assert ratings["ml_closed"]["distribution"]["5"] == 1
    assert ratings["ml_closed"]["average"] == 5.0
    assert ratings["escalated"]["average"] == 3.0
    # Все пять делений присутствуют, даже нулевые — фронт рисует полную шкалу.
    assert sorted(ratings["overall"]["distribution"]) == ["1", "2", "3", "4", "5"]


async def test_support_line_breakdown(client: AsyncClient) -> None:
    first = await _create(client, support_line="first")
    await _close(client, first["id"], score=4)
    await _create(client, support_line="third")

    lines = {item["support_line"]: item for item in (await _overview(client))["by_support_line"]}
    assert lines["first"]["closed_by_ml"] == 1
    assert lines["first"]["rating"]["average"] == 4.0
    assert lines["third"]["total"] == 1
    assert lines["third"]["closed"] == 0


async def test_period_filter_excludes_older_tickets(client: AsyncClient) -> None:
    ticket = await _create(client)
    await _close(client, ticket["id"], score=1)

    response = await client.get(f"{API}/analytics/overview", params={"date_from": "2999-01-01"})
    assert response.status_code == 200
    body = response.json()
    assert body["totals"]["total"] == 0
    assert body["ratings"]["overall"]["count"] == 0
