"""Tests for Momentum agent seats (queue item e9, exec-seats).

Covers the accept bar directly: claim, ratify (by the CEO holder, and by the
owner when no CEO has been ratified yet), owner veto (reopen, regardless of
who claimed/ratified), and organization isolation. The ``#exec``
Team-channel handler and the router that will call these functions are a
later slice (this one mirrors the Momo Board's own b1/b4 split: persistence
+ workflow first, wiring after).
"""

from __future__ import annotations

import pytest
from org_isolation_fixtures import ORG_A, ORG_B, USER_A, USER_B, acting_as, org_world  # noqa: F401

from deerflow.exec_seats import SeatAuthorizationError, SeatTransitionError, assert_can_claim, assert_can_ratify, assert_can_reopen
from deerflow.persistence.exec_seats import AgentSeatRepository, AgentSeatStatus

CEO_SEAT = "CEO (chief of staff)"
CMO_SEAT = "CMO"


@pytest.mark.asyncio
async def test_claim_creates_a_seat_with_claimed_status(org_world):  # noqa: F811
    repo = AgentSeatRepository(org_world)
    with acting_as(USER_A, ORG_A):
        assert_can_claim(None)
        seat = await repo.claim_seat(seat=CMO_SEAT, agent_name="cmo-agent", scope="content, SEO/AEO", kpi="qualified leads", weekly_token_budget=1000, claimed_by_user_id=USER_A)
    assert seat["status"] == AgentSeatStatus.CLAIMED
    assert seat["seat"] == CMO_SEAT
    assert seat["agent_name"] == "cmo-agent"


@pytest.mark.asyncio
async def test_owner_ratifies_the_first_ceo_claim(org_world):  # noqa: F811
    """Bootstrap case: nobody holds the ratified CEO seat yet, so the owner ratifies."""
    repo = AgentSeatRepository(org_world)
    with acting_as(USER_A, ORG_A):
        seat = await repo.claim_seat(seat=CEO_SEAT, agent_name="ceo-agent")
        assert await repo.ratified_holder(CEO_SEAT) is None

        assert_can_ratify(seat["status"], actor_is_ceo=False, actor_is_owner=True)
        ratified = await repo.patch_seat(seat["id"], status=AgentSeatStatus.RATIFIED, ratified_by_user_id=USER_A)
    assert ratified["status"] == AgentSeatStatus.RATIFIED
    assert ratified["ratified_by_user_id"] == USER_A


@pytest.mark.asyncio
async def test_ceo_holder_ratifies_a_non_ceo_claim(org_world):  # noqa: F811
    repo = AgentSeatRepository(org_world)
    with acting_as(USER_A, ORG_A):
        cmo_seat = await repo.claim_seat(seat=CMO_SEAT, agent_name="cmo-agent")

        # The acting agent holds the already-ratified CEO seat.
        assert_can_ratify(cmo_seat["status"], actor_is_ceo=True, actor_is_owner=False)
        ratified = await repo.patch_seat(cmo_seat["id"], status=AgentSeatStatus.RATIFIED, ratified_by_user_id="ceo-agent")
    assert ratified["status"] == AgentSeatStatus.RATIFIED


@pytest.mark.asyncio
async def test_ratify_by_neither_ceo_nor_owner_is_rejected(org_world):  # noqa: F811
    repo = AgentSeatRepository(org_world)
    with acting_as(USER_A, ORG_A):
        seat = await repo.claim_seat(seat=CMO_SEAT, agent_name="cmo-agent")

        with pytest.raises(SeatAuthorizationError):
            assert_can_ratify(seat["status"], actor_is_ceo=False, actor_is_owner=False)

        # The rejected attempt never wrote anything: the seat is still claimed.
        unchanged = await repo.get_seat(seat["id"])
    assert unchanged["status"] == AgentSeatStatus.CLAIMED


@pytest.mark.asyncio
async def test_ratify_from_a_non_claimed_status_is_rejected(org_world):  # noqa: F811
    with pytest.raises(SeatTransitionError):
        assert_can_ratify(AgentSeatStatus.RATIFIED, actor_is_ceo=True, actor_is_owner=False)
    with pytest.raises(SeatTransitionError):
        assert_can_ratify(AgentSeatStatus.REOPENED, actor_is_ceo=False, actor_is_owner=True)


@pytest.mark.asyncio
async def test_owner_veto_reopens_a_ratified_seat_regardless_of_holder(org_world):  # noqa: F811
    """EXECUTIVE.md rule 4 (owner only): reassigning any title."""
    repo = AgentSeatRepository(org_world)
    with acting_as(USER_A, ORG_A):
        seat = await repo.claim_seat(seat=CMO_SEAT, agent_name="cmo-agent")
        ratified = await repo.patch_seat(seat["id"], status=AgentSeatStatus.RATIFIED, ratified_by_user_id="ceo-agent")

        assert_can_reopen(ratified["status"], actor_is_owner=True)
        reopened = await repo.patch_seat(seat["id"], status=AgentSeatStatus.REOPENED)
    assert reopened["status"] == AgentSeatStatus.REOPENED

    # The seat can be claimed again after the veto.
    assert_can_claim(reopened["status"])


@pytest.mark.asyncio
async def test_non_owner_veto_is_rejected(org_world):  # noqa: F811
    repo = AgentSeatRepository(org_world)
    with acting_as(USER_A, ORG_A):
        seat = await repo.claim_seat(seat=CMO_SEAT, agent_name="cmo-agent")
        ratified = await repo.patch_seat(seat["id"], status=AgentSeatStatus.RATIFIED, ratified_by_user_id="ceo-agent")

        with pytest.raises(SeatAuthorizationError):
            assert_can_reopen(ratified["status"], actor_is_owner=False)

        # The rejected veto never wrote anything: the seat is still ratified.
        unchanged = await repo.get_seat(seat["id"])
    assert unchanged["status"] == AgentSeatStatus.RATIFIED


@pytest.mark.asyncio
async def test_claim_on_an_already_ratified_seat_is_rejected(org_world):  # noqa: F811
    with pytest.raises(SeatTransitionError):
        assert_can_claim(AgentSeatStatus.RATIFIED)
    with pytest.raises(SeatTransitionError):
        assert_can_claim(AgentSeatStatus.CLAIMED)


@pytest.mark.asyncio
async def test_org_isolation_a_seat_in_one_org_is_invisible_from_another(org_world):  # noqa: F811
    repo = AgentSeatRepository(org_world)
    with acting_as(USER_A, ORG_A):
        seat = await repo.claim_seat(seat=CMO_SEAT, agent_name="cmo-agent")

    with acting_as(USER_B, ORG_B):
        foreign_get = await repo.get_seat(seat["id"])
        foreign_list = await repo.list_seats()
        foreign_holder = await repo.ratified_holder(CMO_SEAT)
    assert foreign_get is None
    assert foreign_list == []
    assert foreign_holder is None

    # Momentum's own organization still sees it.
    with acting_as(USER_A, ORG_A):
        own_list = await repo.list_seats()
    assert [s["id"] for s in own_list] == [seat["id"]]
