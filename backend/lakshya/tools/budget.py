"""Reserve maximum billable usage before a call; failed calls retain the reservation."""

from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from lakshya.config import Settings
from lakshya.db.models import BudgetReservation


class Budget:
    def __init__(self, engine: Engine, settings: Settings, run_id: str, agent_id: str) -> None:
        self.engine, self.settings, self.run_id, self.agent_id = engine, settings, run_id, agent_id

    def reserve(self, tokens: int, cost: float) -> str:
        day = datetime.now(ZoneInfo(self.settings.timezone)).date().isoformat()
        with self.engine.connect() as connection:
            if self.engine.dialect.name == "sqlite":
                connection.exec_driver_sql("BEGIN IMMEDIATE")
            else:
                connection.begin()
                # Serialize reservations across workers on PostgreSQL too.
                connection.exec_driver_sql("SELECT pg_advisory_xact_lock(73493211)")
            try:
                with Session(bind=connection) as session:
                    rows = list(session.scalars(select(BudgetReservation)))
                    for subset, token_cap, cost_cap, call_cap in (
                        (
                            [r for r in rows if r.run_id == self.run_id],
                            self.settings.max_run_tokens,
                            self.settings.max_run_cost_usd,
                            self.settings.max_run_llm_calls,
                        ),
                        (
                            [r for r in rows if r.local_day == day],
                            self.settings.max_day_tokens,
                            self.settings.max_day_cost_usd,
                            self.settings.max_day_llm_calls,
                        ),
                    ):
                        if len(subset) >= call_cap:
                            raise ValueError(
                                "LLM request quota exhausted; no additional call allowed"
                            )
                        used_tokens = sum(
                            r.actual_tokens if r.actual_tokens is not None else r.reserved_tokens
                            for r in subset
                        )
                        used_cost = sum(
                            r.actual_cost_usd
                            if r.actual_cost_usd is not None
                            else r.reserved_cost_usd
                            for r in subset
                        )
                        if used_tokens + tokens > token_cap or used_cost + cost > cost_cap:
                            raise ValueError(
                                "Token/cost budget exhausted; no additional LLM call allowed"
                            )
                    row = BudgetReservation(
                        run_id=self.run_id,
                        agent_run_id=self.agent_id,
                        local_day=day,
                        reserved_tokens=tokens,
                        reserved_cost_usd=cost,
                    )
                    session.add(row)
                    session.flush()
                    identity = row.id
                connection.commit()
                return identity
            except Exception:
                connection.rollback()
                raise

    def settle(self, identity: str, tokens: int, cost: float) -> None:
        with Session(self.engine) as session, session.begin():
            row = session.get(BudgetReservation, identity)
            if row is None:
                raise ValueError("Missing usage reservation")
            row.actual_tokens, row.actual_cost_usd, row.state = tokens, cost, "completed"
