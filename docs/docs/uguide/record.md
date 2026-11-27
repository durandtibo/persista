# Records

:book: This page describes the `persista.record` package, which provides a generic `Record`
container, utilities to filter/sort collections of records by metadata, a `RecordStore` built on
top of `persista.store`, and a `persista.record.analysis` subpackage of data-quality checks
(deduplication, diffing, schema drift, and more) for corpora of records.

**Prerequisites:** You'll need to know a bit of Python, and it helps to be familiar with the
[store user guide](store.md) since `RecordStore` is backed by a `BaseStore`.

## Overview

The `persista.record` package provides:

- `Record`: an immutable container pairing a stable `id` with an arbitrary `metadata` dict
- `filter_by_metadata` / `filter_by_metadata_range` / `filter_by_metadata_values`: filter a list
  of records by their metadata
- `sort_by_metadata`: sort a list of records by a metadata key
- `persista.record.fake.generate_fake_records`: generate synthetic records for tests and demos
  (requires the `faker` extra)
- `persista.record.store`: `RecordStore`, to persist records in any `persista.store` backend
- `persista.record.analysis`: functions to check a corpus of records for exact/near duplicates,
  id collisions, orphan references, schema drift, and other data-quality issues

## The `Record` Container

A `Record` pairs an `id` with a `metadata` dict. Use `Record.from_metadata` to derive a stable
UUID `id` from the metadata itself, so two records with the same metadata contents get the same
`id` regardless of key insertion order:

```pycon
>>> from persista.record import Record
>>> record = Record.from_metadata({"source": "cats.txt", "page": 1})
>>> record.metadata
mappingproxy({'source': 'cats.txt', 'page': 1})

```

A `Record` can also be constructed directly with an explicit `id`:

```pycon
>>> from persista.record import Record
>>> record = Record(id="doc-1", metadata={"source": "cats.txt"})
>>> record.id
'doc-1'

```

## Filtering and Sorting Records

`filter_by_metadata` keeps records whose metadata field equals a given value:

```pycon
>>> from persista.record import Record, filter_by_metadata
>>> records = [
...     Record(id="a", metadata={"category": "Science"}),
...     Record(id="b", metadata={"category": "Cooking"}),
...     Record(id="c", metadata={"category": "Science"}),
... ]
>>> [r.id for r in filter_by_metadata(records, "category", "Science")]
['a', 'c']

```

`filter_by_metadata_range` keeps records whose metadata field falls within an inclusive
`[lower, upper]` range (either bound can be omitted), and `filter_by_metadata_values` keeps
records whose metadata field is a member of a given set of values:

```pycon
>>> from persista.record import Record, filter_by_metadata_range, filter_by_metadata_values
>>> records = [
...     Record(id="a", metadata={"page": 1, "category": "Science"}),
...     Record(id="b", metadata={"page": 5, "category": "Cooking"}),
...     Record(id="c", metadata={"page": 10, "category": "History"}),
... ]
>>> [r.id for r in filter_by_metadata_range(records, "page", lower=2, upper=8)]
['b']
>>> [r.id for r in filter_by_metadata_values(records, "category", {"Science", "History"})]
['a', 'c']

```

`sort_by_metadata` sorts records by a metadata key, placing records missing that key at the end
by default:

```pycon
>>> from persista.record import Record, sort_by_metadata
>>> records = [
...     Record(id="b", metadata={"source": "b.txt"}),
...     Record(id="a", metadata={"source": "a.txt"}),
...     Record(id="c"),
... ]
>>> [r.id for r in sort_by_metadata(records, "source")]
['a', 'b', 'c']
>>> [r.id for r in sort_by_metadata(records, "source", reverse=True, keep_missing=False)]
['b', 'a']

```

## Generating Fake Records

`generate_fake_records` (requires the `faker` extra) generates synthetic records with a fake
author name and topic, useful for tests, demos, and prototyping:

```pycon
>>> from persista.record.fake import generate_fake_records
>>> records = generate_fake_records(n=3, seed=42)
>>> [record.id for record in records]
['rec-0', 'rec-1', 'rec-2']

```

## Persisting Records with `RecordStore`

`RecordStore` wraps any `persista.store.BaseStore` to store `Record` instances, keyed by their
`id`. It is the only record store: choose where the records are persisted by choosing the store,
for example `RecordStore(InMemoryStore())` for tests and prototyping, or
`RecordStore(SQLiteStore(path))` to persist them in a SQLite database:

```pycon
>>> from persista.record import Record
>>> from persista.record.store import RecordStore
>>> from persista.store import SQLiteStore
>>> with RecordStore(SQLiteStore(":memory:")) as store:
...     store.set_many([Record(id="1", metadata={"author": "Alice"})])
...     store.get("1")
Record(id='1', metadata={'author': 'Alice'})

```

`RecordStore` has the method names of `BaseStore`, with records in place of key-value pairs, and
each method has an `a`-prefixed asynchronous twin (`aget`, `aset_many`, `afilter`, ...):

- `set`, `set_many`, `set_batches`: write one record, a list of records, or a stream of records
- `get`, `get_many`, `contains`, `contains_many`: read records by id
- `filter`: retrieve the records matching metadata fields
- `delete`, `delete_many`, `clear`: remove records
- `keys`, `values`, `iter_batches`, `count`: iterate over the records and count them
- `open`, `close`, `closed`: manage the underlying store

The metadata of a record is stored as a value of the underlying store, so the
[codec of the store](store.md#values-and-codecs) decides which metadata it accepts. For example,
`RecordStore(InMemoryStore())` only accepts metadata that JSON can represent, and returns a tuple
as a list; use `RecordStore(InMemoryStore(codec=PickleCodec()))` to keep Python types.

A [store URI](store.md#store-uris) belongs to the underlying store: use
`record_store.store.to_uri()`, and `RecordStore(store_from_uri(uri))` to reconnect.

### Handling Conflicts

`set`, `set_many` and `set_batches` accept the keyword-only argument `on_conflict`, with the
[strategies of the stores](store.md#handling-conflicts): `"overwrite"` (default), `"raise"`,
`"skip"` and `"merge"` (a shallow merge of the metadata):

```pycon
>>> from persista.record import Record
>>> from persista.record.store import RecordStore
>>> from persista.store import InMemoryStore
>>> with RecordStore(InMemoryStore()) as store:
...     store.set(Record(id="1", metadata={"author": "Alice"}))
...     store.set(Record(id="1", metadata={"year": 2024}), on_conflict="merge")
...     store.get("1")
Record(id='1', metadata={'author': 'Alice', 'year': 2024})

```

When a list given to `set_many` contains several records with the same `id`, they are resolved
with the same strategy, in the order of the list: `"overwrite"` keeps the last one, `"skip"` the
first one, `"merge"` merges them, and `"raise"` raises a `KeyError` and writes nothing.
`set_batches` writes one batch at a time, so with `"raise"` the batches written before the
conflict are kept.

### Filtering Records

`filter` retrieves the records matching all the given metadata keyword arguments, combined with
`AND`. It follows the `filter` semantics of the underlying store, so the way values are compared,
and the field names that are accepted, depend on the backend. The SQL stores filter in the database
(see [indexing a filtered field](store.md#indexing-a-filtered-field)); the other stores are scanned:

```pycon
>>> from persista.record import Record
>>> from persista.record.store import RecordStore
>>> from persista.store import InMemoryStore
>>> with RecordStore(InMemoryStore()) as store:
...     store.set_many(
...         [
...             Record(id="1", metadata={"author": "Alice", "category": "Programming"}),
...             Record(id="2", metadata={"author": "Bob", "category": "Programming"}),
...         ]
...     )
...     len(store.filter(category="Programming"))
2

```

### Building a Record Store from a Configuration

`persista` has no factory classes. To describe a record store in a configuration, use
`resolve_object` from [`coola.factory`](https://github.com/durandtibo/coola): the `_target_` key is
the fully qualified name of the class, and the other keys are the arguments of its constructor.
`resolve_object` does not build a configuration nested in another one, so build the store first and
pass it to the `RecordStore`:

```pycon
>>> from coola.factory import resolve_object
>>> from persista.record import Record
>>> from persista.record.store import RecordStore
>>> from persista.store import BaseStore
>>> config = {
...     "_target_": "persista.record.store.RecordStore",
...     "store": {"_target_": "persista.store.SQLiteStore", "database": ":memory:"},
... }
>>> store = resolve_object(config["store"], cls=BaseStore)
>>> with resolve_object({**config, "store": store}, cls=RecordStore) as record_store:
...     record_store.set_many([Record(id="1", metadata={"author": "Alice"})])
...     record_store.get("1")
Record(id='1', metadata={'author': 'Alice'})

```

Only use `resolve_object` with a configuration from a trusted source, because it imports and calls
whatever `_target_` names. See
[building a store from a configuration](store.md#building-a-store-from-a-configuration).

## Analyzing a Corpus of Records

`persista.record.analysis` provides single-pass, streaming-friendly checks over a corpus of
records (a list, generator, or other iterable) to spot data-quality issues before they cause
problems downstream.

### Exact and Approximate Duplicate Detection

`find_duplicate_record_ids` groups record ids that share byte-for-byte identical metadata:

```pycon
>>> from persista.record import Record
>>> from persista.record.analysis import find_duplicate_record_ids
>>> records = [
...     Record(id="a", metadata={"source": "a.pdf"}),
...     Record(id="b", metadata={"source": "a.pdf"}),
...     Record(id="c", metadata={"source": "b.pdf"}),
... ]
>>> find_duplicate_record_ids(records)
[['a', 'b']]

```

`count_approx_duplicate_records` estimates the same thing using a Bloom filter, with fixed (O(1))
memory usage regardless of corpus size, at the cost of a tunable false-positive rate — useful when
a corpus is too large for the exact hash groups above to fit in memory:

```pycon
>>> from persista.record import Record
>>> from persista.record.analysis import count_approx_duplicate_records
>>> records = [
...     Record(id="a", metadata={"source": "a.pdf"}),
...     Record(id="b", metadata={"source": "a.pdf"}),
...     Record(id="c", metadata={"source": "b.pdf"}),
... ]
>>> count_approx_duplicate_records(records, expected_record_count=1000)
1

```

`find_near_duplicate_record_ids` catches records whose metadata overlaps substantially but not
completely (e.g. the same document re-ingested with one extra or corrected field), using MinHash
signatures and locality-sensitive hashing (LSH):

```pycon
>>> from persista.record import Record
>>> from persista.record.analysis import find_near_duplicate_record_ids
>>> records = [
...     Record(id="a", metadata={"source": "a.pdf", "page": 1, "lang": "en"}),
...     Record(id="b", metadata={"source": "a.pdf", "page": 1, "lang": "fr"}),
...     Record(id="c", metadata={"source": "z.pdf", "page": 9}),
... ]
>>> find_near_duplicate_record_ids(records, num_hashes=4, num_bands=4)
[['a', 'b']]

```

### Id Collisions

`find_id_collisions` flags the _same_ id appearing more than once with _different_ metadata,
which usually indicates an id-generation bug rather than a legitimate duplicate:

```pycon
>>> from persista.record import Record
>>> from persista.record.analysis import find_id_collisions
>>> records = [
...     Record(id="a", metadata={"source": "x.pdf"}),
...     Record(id="a", metadata={"source": "y.pdf"}),
... ]
>>> find_id_collisions(records)
{'a': [{'source': 'x.pdf'}, {'source': 'y.pdf'}]}

```

### Diffing Two Snapshots

`diff_records` compares a "before" and "after" snapshot by id, reporting records added, removed,
or whose metadata changed — useful for auditing what an ingestion or transformation step changed:

```pycon
>>> from persista.record import Record
>>> from persista.record.analysis import diff_records
>>> before = [
...     Record(id="a", metadata={"source": "a.pdf"}),
...     Record(id="b", metadata={"source": "b.pdf"}),
... ]
>>> after = [
...     Record(id="a", metadata={"source": "a.pdf", "page": 1}),
...     Record(id="c", metadata={"source": "c.pdf"}),
... ]
>>> diff_records(before, after)
{'added': ['c'], 'removed': ['b'], 'changed': ['a']}

```

### Orphan References

`find_orphan_references` finds records whose metadata references another record's id (e.g. a
`"parent_id"` for a chunk pointing back at the document it came from) that does not exist in the
corpus. Unlike the other analyses, this requires a re-iterable collection (not a one-shot
generator), since it makes two passes over `records`:

```pycon
>>> from persista.record import Record
>>> from persista.record.analysis import find_orphan_references
>>> records = [
...     Record(id="doc1", metadata={}),
...     Record(id="chunk1", metadata={"parent_id": "doc1"}),
...     Record(id="chunk2", metadata={"parent_id": "missing_doc"}),
... ]
>>> find_orphan_references(records, reference_key="parent_id")
['chunk2']

```

### Schema Shapes and Value Frequency

`compute_schema_shapes` groups record ids by the _shape_ of their metadata (the set of keys
present, ignoring values), which surfaces schema drift across a corpus:

```pycon
>>> from persista.record import Record
>>> from persista.record.analysis import compute_schema_shapes
>>> records = [
...     Record(id="a", metadata={"source": "a.pdf", "page": 1}),
...     Record(id="b", metadata={"source": "b.pdf", "page": 2}),
...     Record(id="c", metadata={"source": "c.pdf"}),
... ]
>>> compute_schema_shapes(records)
{('page', 'source'): ['a', 'b'], ('source',): ['c']}

```

`compute_value_frequency` reports, for each metadata key, its most common values (top-K) and an
approximate cardinality (via HyperLogLog) — useful for spotting near-constant keys or keys
unsuitable for grouping/joins because of excessive uniqueness (e.g. UUIDs):

```pycon
>>> from persista.record import Record
>>> from persista.record.analysis import compute_value_frequency
>>> records = [
...     Record(id="a", metadata={"lang": "en"}),
...     Record(id="b", metadata={"lang": "en"}),
...     Record(id="c", metadata={"lang": "fr"}),
... ]
>>> result = compute_value_frequency(records)
>>> result["lang"]["top_values"]
[('en', 2), ('fr', 1)]

```

### Metadata Stats and Reporting

`compute_metadata_stats` streams over a corpus and reports keys-per-record statistics and, for
each metadata key, presence counts, value types, and a sample of unique values:

```pycon
>>> from persista.record import Record
>>> from persista.record.analysis import compute_metadata_stats
>>> records = [
...     Record(id="a", metadata={"source": "a.pdf"}),
...     Record(id="b", metadata={"source": "b.pdf", "page": 1}),
... ]
>>> stats = compute_metadata_stats(records)
>>> stats["count"]
2

```

`print_metadata_stats_report` (requires the `rich` extra) pretty-prints a stats dict from
`compute_metadata_stats` as an overview line, a summary table, and a per-key breakdown table:

```python
from persista.record import Record
from persista.record.analysis import compute_metadata_stats, print_metadata_stats_report

records = [Record(id="a", metadata={"source": "a.pdf"})]
print_metadata_stats_report(compute_metadata_stats(records), title="My Corpus")
```

## API Reference

See the [reference documentation](../refs/record.md) for the full API.
