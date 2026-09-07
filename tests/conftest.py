from __future__ import annotations

import contextlib
import datetime as dt
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from viejoolbel import db as db_module
from viejoolbel.bell import BellController
from viejoolbel.config import Settings
from viejoolbel.hardware.mock import MockHardware
from viejoolbel.scheduler import BellScheduler
from viejoolbel.service import Service


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        data_dir=tmp_path / "data",
        hardware="mock",
        secret_key="test-secret",
        timezone="Europe/Brussels",
    )


@pytest.fixture
def initialized_db(settings: Settings) -> Iterator[None]:
    settings.ensure_dirs()
    db_module.init_engine(settings.db_path)
    yield
    db_module._SESSION_FACTORY = None  # reset global between tests


@pytest.fixture
def hardware() -> MockHardware:
    return MockHardware()


@pytest.fixture
def controller(initialized_db, hardware: MockHardware, settings: Settings) -> BellController:
    return BellController(hardware, settings)


@pytest.fixture
def scheduler(controller: BellController, settings: Settings) -> Iterator[BellScheduler]:
    sch = BellScheduler(controller, settings.timezone)
    yield sch
    with contextlib.suppress(Exception):
        sch.shutdown()


@pytest.fixture
def service(settings: Settings) -> Iterator[Service]:
    svc = Service(settings)
    yield svc
    svc.stop()
    db_module._SESSION_FACTORY = None


@pytest.fixture
def client(service: Service) -> Iterator[TestClient]:
    app = service.build_app()
    with TestClient(app) as c:
        yield c


@pytest.fixture
def auth_client(client: TestClient) -> TestClient:
    resp = client.post(
        "/login", data={"username": "admin", "password": "changeme"}, follow_redirects=False
    )
    assert resp.status_code == 303
    return client


def a_date(y: int, m: int, d: int) -> dt.date:
    return dt.date(y, m, d)
