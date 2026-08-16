# feat/redaction — Spec

**Task 2 · Depends on: 1 · Files:** `agentaudit/core/redaction.py`, `tests/test_redaction.py`

## Goal
Strip secrets/PII from evidence before it is stored or displayed. Core to the product —
we test *private* company agents.

## Public API
```python
class RedactionPattern(BaseModel):
    name: str
    regex: str                           # matched with re.IGNORECASE unless anchored

class RedactionConfig(BaseModel):
    patterns: list[RedactionPattern] = []     # extra, on top of built-ins
    literals: list[str] = []                  # exact strings to mask (e.g. known secrets)
    use_builtins: bool = True

class EvidencePolicy(BaseModel):
    store_request: bool = True
    store_response: bool = True
    redact: RedactionConfig = RedactionConfig()

class Redactor:
    def __init__(self, config: RedactionConfig): ...
    def redact(self, value: Any) -> Any     # recurses str|dict|list; returns masked copy
    def redact_text(self, text: str) -> str
```

## Built-in patterns (when `use_builtins`)
| name | regex (illustrative) |
|------|------|
| api_key | `sk-[A-Za-z0-9_-]{8,}` |
| bearer | `Bearer\s+[A-Za-z0-9._-]+` |
| email | `[\w.+-]+@[\w-]+\.[\w.-]+` |
| iban | `[A-Z]{2}\d{2}[A-Z0-9]{10,30}` |
| card | `\b(?:\d[ -]*?){13,16}\b` |
| account | `\b\d{8,17}\b` (long digit runs) |
| phone | `\+?\d[\d ()-]{7,}\d` |

Mask format: replace match with `«redacted:{name}»`. Literals → `«redacted»`.

## Behavior
- `redact` deep-copies; never mutates input. Dict **keys** are not redacted, values are.
- Order: literals first, then built-ins, then extra patterns.
- Applied by the **runner** (task 11) to `request`/`response` and by **store** (task 13) as a
  final safety net. If `store_request/response` is False, that field is set to `None`
  (not stored at all), independent of redaction.

## Failure behavior
- Invalid user regex → raise `ValueError("invalid redaction pattern '{name}': …")` at
  `Redactor` construction (fail fast, not per-call).

## Examples
```python
r = Redactor(RedactionConfig())
r.redact({"headers": {"Authorization": "Bearer abc.def"}, "body": "mail me a@b.com"})
# -> {"headers": {"Authorization": "«redacted:bearer»"}, "body": "mail me «redacted:email»"}
```

## Tests required
- API key `sk-...`, email, IBAN, 16-digit account number all masked.
- Nested dict/list payload masked recursively; original object unchanged.
- `store_request=False` → runner/store persists `request=None`.
- Bad custom regex raises at construction.

## Done when
Given a payload containing seeded secrets, `Redactor.redact` output contains none of them,
and evidence-policy flags control storage.
