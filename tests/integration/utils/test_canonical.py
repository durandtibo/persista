r"""Check that the canonical encoding does not depend on the process that
computes it.

The iteration order of a set of strings depends on ``PYTHONHASHSEED``,
so the values are encoded in fresh interpreters with different seeds.
"""

from __future__ import annotations

import asyncio
import os
import sys

import pytest

# A value with sets, and with a dict whose insertion order depends on the
# hashes of the strings.
VALUE = r"""
words = {f"word-{i}" for i in range(50)}
value = [
    words,
    frozenset(w.encode() for w in words),
    {word: len(word) for word in sorted(words, key=hash)},
    (None, True, -(10**30), -0.0, float("nan"), chr(0xD800)),
    {frozenset(words), "word"},
]
"""

SEEDS = ("0", "1", "2", "12345")


async def run_with_seed(code: str, seed: str) -> str:
    r"""Run some code, after the definition of the value, in a new
    interpreter with a hash seed, and return its output."""
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        f"{VALUE}\n{code}",
        env={**os.environ, "PYTHONHASHSEED": seed},
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    output, errors = await process.communicate()
    if process.returncode:
        raise RuntimeError(errors.decode())
    return output.decode()


async def run_with_seeds(code: str) -> list[str]:
    r"""Run some code with each hash seed, and return the outputs."""
    return await asyncio.gather(*(run_with_seed(code, seed) for seed in SEEDS))


######################################
#     Tests for encode_canonical     #
######################################


@pytest.mark.parametrize("code", ["print(list(words))", "print(list(value[2]))"])
async def test_order_depends_on_hash_seed(code: str) -> None:
    """Test that the seeds change the order of the sets and the dicts,
    so that the test below checks something."""
    assert len(set(await run_with_seeds(code))) == len(SEEDS)


async def test_encode_canonical_same_in_every_process() -> None:
    """Test that a value has the same encoding in processes with
    different hash seeds."""
    outputs = await run_with_seeds(
        "from persista.utils.canonical import encode_canonical\n"
        "print(encode_canonical(value).hex())"
    )
    assert len(set(outputs)) == 1
