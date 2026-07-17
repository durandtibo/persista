from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from persista.testing.fixtures import psycopg_available
from persista.utils.imports import is_psycopg_available

if TYPE_CHECKING:
    from collections.abc import Generator

if is_psycopg_available():
    from testcontainers.postgres import PostgresContainer

try:
    from docker.errors import DockerException
except ImportError:  # pragma: no cover
    DockerException = Exception  # type: ignore[assignment,misc]


def _docker_available() -> bool:
    if not is_psycopg_available():
        return False
    try:
        container = PostgresContainer("postgres:16-alpine")
        container.start()
    except DockerException:
        return False
    container.stop()
    return True


docker_available = pytest.mark.skipif(not _docker_available(), reason="Requires Docker")


@pytest.fixture(scope="session")
def postgres_container() -> Generator[PostgresContainer, None, None]:
    with PostgresContainer("postgres:16-alpine") as container:
        yield container


@pytest.fixture(scope="session")
def conninfo(postgres_container: PostgresContainer) -> str:
    return (
        f"postgresql://{postgres_container.username}:{postgres_container.password}"
        f"@{postgres_container.get_container_host_ip()}"
        f":{postgres_container.get_exposed_port(5432)}"
        f"/{postgres_container.dbname}"
    )


@psycopg_available
@docker_available
def test_conninfo_connects(conninfo: str) -> None:
    import psycopg

    with psycopg.connect(conninfo) as conn, conn.cursor() as cur:
        cur.execute("SELECT 1")
        assert cur.fetchone() == (1,)
