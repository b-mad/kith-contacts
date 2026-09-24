"""Sample data loader (I-05)."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import Contact
from scripts import seed as seed_module
from scripts.seed import ProductionRefused, reset, run, samples, seed
from tests.conftest import make_settings


def test_samples_are_about_fifty_and_reference_real_managers() -> None:
    items = samples()
    names = {s.name for s in items}
    assert len(items) == 50
    assert len(names) == 50
    assert {s.type for s in items} == {"Employee", "Customer", "Vendor"}
    for s in items:
        assert s.manager is None or s.manager in names
    # managers appear before their reports so they can be linked in one pass
    order = [s.name for s in items]
    assert all(order.index(s.manager) < order.index(s.name) for s in items if s.manager)


def test_seed_creates_contacts_with_manager_chains(db_session: Session) -> None:
    added = seed(db_session)

    maria = db_session.scalars(select(Contact).where(Contact.display_name == "Maria Lopez")).one()
    dev = db_session.scalars(select(Contact).where(Contact.display_name == "Dev Patel")).one()
    assert added == 50
    assert dev.manager_id == maria.id
    assert maria.manager is not None
    assert maria.manager.display_name == "Priya Raman"
    assert all(e.email.endswith(".example") for c in [maria, dev] for e in c.emails)


def test_reset_deletes_all_contacts(db_session: Session) -> None:
    seed(db_session)
    reset(db_session)
    assert db_session.scalar(select(func.count()).select_from(Contact)) == 0


@pytest.mark.req("I-05")
def test_seed_refuses_production(settings: Settings) -> None:
    prod = make_settings(str(settings.database_url), app_env="production")
    with pytest.raises(ProductionRefused, match="APP_ENV=production"):
        run(prod)
    with pytest.raises(ProductionRefused):
        run(prod, do_reset=True)


@pytest.mark.req("I-05")
def test_cli_refuses_production(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    env = tmp_path / "prod.env"
    env.write_text(
        "INSTANCE_NAME=Business\nAPP_ENV=production\nPORT=5170\n"
        "DATABASE_URL=postgresql://nobody:x@127.0.0.1:1/none\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("INSTANCE_ENV_FILE", str(env))

    assert seed_module.main([]) == 2
    assert "Refusing to seed" in capsys.readouterr().err


def test_run_seeds_a_development_database(admin_url: str) -> None:
    import uuid

    import psycopg
    from psycopg import sql

    from tests.conftest import _database_url

    name = f"contacts_test_seed_{uuid.uuid4().hex[:6]}"
    with psycopg.connect(admin_url, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    try:
        dev = make_settings(_database_url(name), app_env="development")
        assert run(dev) == 50
        assert run(dev, do_reset=True) == 50  # reset first, so still 50 rather than 100
    finally:
        with psycopg.connect(admin_url, autocommit=True) as conn:
            conn.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name))
            )
