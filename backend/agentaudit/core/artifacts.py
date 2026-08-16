"""Canonical artifact key construction.

Structured evidence stays in Postgres (`test_results.result_json`), which is
already org-scoped and already redacted twice. This module governs the *other*
kind of evidence: blobs. Traces, screenshots, and generated reports do not exist
yet, but the first component that writes one inherits none of that scoping
unless the layout is fixed before it is written.

So the prefix is mandatory and fixed from day one:

    {org_id}/{run_id}/{artifact_id}

`artifact_key` is the only permitted way to build it. Nothing else concatenates
these parts, which is what makes swapping local paths for object storage a
backend change rather than a migration -- and what makes a missing `org_id` a
`TypeError` instead of a blob at the root of a shared bucket.
"""

from __future__ import annotations

import posixpath
import re

# Deliberately strict: artifact ids are minted by us, not supplied by a tenant,
# so there is no legitimate reason for one to contain a separator or a dot run.
_SEGMENT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")


class ArtifactKeyError(ValueError):
    """A key component that would escape its org/run prefix."""


def _validated(name: str, value: str) -> str:
    if not isinstance(value, str) or not value:
        raise ArtifactKeyError(f"{name} must be a non-empty string")
    if value != value.strip():
        raise ArtifactKeyError(f"{name} must not be padded with whitespace")
    if "/" in value or "\\" in value:
        raise ArtifactKeyError(f"{name} must not contain a path separator: {value!r}")
    if value.startswith("/") or (len(value) > 1 and value[1] == ":"):
        raise ArtifactKeyError(f"{name} must be relative, not absolute: {value!r}")
    if ".." in value:
        raise ArtifactKeyError(f"{name} must not contain '..': {value!r}")
    if not _SEGMENT_RE.match(value):
        raise ArtifactKeyError(f"{name} has characters not allowed in a key: {value!r}")
    return value


def artifact_key(org_id: str, run_id: str, artifact_id: str) -> str:
    """Build the one legal storage key for an artifact.

    `org_id` is a required positional argument on purpose: a caller that has not
    established which tenant it is acting for cannot produce a key at all.
    """
    key = posixpath.join(
        _validated("org_id", org_id),
        _validated("run_id", run_id),
        _validated("artifact_id", artifact_id),
    )
    # Belt and braces: if normalization moves the key, a component escaped.
    if posixpath.normpath(key) != key:
        raise ArtifactKeyError(f"key does not normalize to itself: {key!r}")
    return key
