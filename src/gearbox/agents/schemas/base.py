"""Base schema with version identification for forward/backward compatibility.

All agent result schemas inherit from :class:`VersionedSchema` so that every
persisted artifact carries a ``schema_version`` field.  Load functions can
then validate the version before calling ``model_validate()`` and raise a
clear migration error when the version does not match.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# Current schema version — bump this when any result schema field is
# added, removed, or has its type changed.
SCHEMA_VERSION: Literal["1.0"] = "1.0"


class VersionedSchema(BaseModel):
    """Base class for all versioned agent-result schemas."""

    schema_version: Literal["1.0"] = Field(
        default=SCHEMA_VERSION,
        description="Schema version for artifact compatibility checks",
    )
