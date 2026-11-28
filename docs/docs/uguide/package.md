# Properties of the Package

:book: This page states what `persista` guarantees as a whole, and where these guarantees stop. The
guides of the sub-packages give their own properties: [stores](store.md#properties),
[caching](cache.md#properties), [HTTP](http.md#properties), [records](record.md#properties) and
[utilities and testing](testing.md#properties).

**Prerequisites:** You'll need to know a bit of Python.

## Properties

| Property                                  | Guarantee                                                                                                                                                                     | Limits                                                                                                                                                                                                                                           |
| ----------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| One contract                              | You can change the backend of a store, and so of a cache or a record store, without changing the calling code.                                                                | A backend has [its own limits](store.md#limits-of-the-backends): most raise an error, but `PostgresStore` reads `-0.0` back as `0.0` and does not keep the order of the keys of a value.                                                         |
| Sync and async parity                     | Every operation of a store, a cache or a record store that touches the backend has a sync method and an `a`-prefixed twin with the same arguments, results and errors.        | `persista.http.requests` is sync only. Many concurrent async calls can exceed the connection limit of `RedisStore`. Cancelling an async call that runs in a thread does not stop it.                                                             |
| No silent wrong result                    | An input that cannot be handled raises, and is not confused with another input.                                                                                               | The exceptions are those of `PostgresStore` above, pairs of one batch of `set_batches` [with the same key](store.md#handling-conflicts), and memoized functions [that have the same name](cache.md#limits).                                      |
| Explicit lifecycle                        | A constructor does not connect: `open`/`aopen` do. A closed store, cache or record store raises `RuntimeError` on every operation, also with an empty input.                  | An iterator raises when it is first advanced. An HTTP client wrapper needs no `open`; once its `httpx` client is closed, it raises `RuntimeError`.                                                                                               |
| Optional libraries stay optional and lazy | Outside `persista.testing` (which needs `pytest`), importing a sub-package needs no optional library and imports none. A missing library is reported when it is used.         | The modules `persista.http.requests` and `persista.record.fake` import their library, if it is installed, when they are imported. The constructor of a store or of an HTTP client wrapper raises `RuntimeError` if its library is missing.       |
| Layered                                   | `utils` ← `store` ← `cache` ← `http`, and `store` ← `record`. No library code imports `testing`. The layers are checked in the continuous integration with `import-linter`.   | None.                                                                                                                                                                                                                                            |
| Secrets stay private                      | The representations and the log messages of `persista` and the errors that it raises itself do not show the password of a URL or of a connection string. `to_uri` returns it. | The errors of the libraries are not rewritten: an `httpx` or `requests` error can [show the credentials of a URL](http.md#credentials-in-errors-and-logs). Keys and values can appear in error messages, and cache keys in `DEBUG` log messages. |

## Not Guaranteed

- **Transactions** across several calls.
- **Cancellation**: cancelling an async call that runs in a thread does not stop the operation.
- **`pickle`**: decoding a payload can execute arbitrary code. Only use `PickleCodec` with trusted
  data.

The guides list what else each sub-package does not guarantee.
