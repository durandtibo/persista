r"""Check that the identifier and the serialization of a record do not
depend on the process."""

from __future__ import annotations

import asyncio
import pickle
import sys

import pytest

from persista.record import Record

METADATA = {"tags": {"a", "b", "c", "d"}, "page": 1.0, "nested": {"y": [2], "x": (b"z", None)}}


async def run_python(code: str, data: bytes = b"", seed: str = "0") -> bytes:
    r"""Run some code in a new interpreter with a given hash seed, and
    return what it writes."""
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        code,
        env={"PYTHONHASHSEED": seed},
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    output, errors = await process.communicate(data)
    if process.returncode:
        raise RuntimeError(errors.decode())
    return output


############################
#     Tests for Record     #
############################


@pytest.mark.parametrize("seed", ["1", "2", "3"])
async def test_from_metadata_id_is_the_same_in_another_process(seed: str) -> None:
    """Test that the derived id does not depend on the hash seed of the
    process."""
    code = (
        f"from persista.record import Record\nprint(Record.from_metadata({METADATA!r}).id, end='')"
    )
    assert await run_python(code, seed=seed) == Record.from_metadata(METADATA).id.encode()


@pytest.mark.parametrize("protocol", range(pickle.HIGHEST_PROTOCOL + 1))
async def test_pickled_record_is_loaded_in_another_process(protocol: int) -> None:
    """Test that a record pickled in one process is loaded in another
    one, with every protocol."""
    code = (
        "import pickle, sys\n"
        "record = pickle.load(sys.stdin.buffer)\n"
        "print(type(record.metadata).__name__, record.id, record.metadata == "
        f"{METADATA!r}, end='')"
    )
    data = pickle.dumps(Record(id="1", metadata=METADATA), protocol=protocol)
    assert await run_python(code, data) == b"mappingproxy 1 True"
