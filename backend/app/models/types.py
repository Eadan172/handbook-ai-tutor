from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy.engine import Dialect
from sqlalchemy.types import CHAR, JSON, TypeDecorator, TypeEngine


class GUID(TypeDecorator):
    """Platform-independent UUID."""

    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect) -> TypeEngine[Any]:
        if dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import UUID as PGUUID

            return dialect.type_descriptor(PGUUID(as_uuid=True))
        return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value: Any, dialect: Dialect) -> Any:
        if value is None:
            return value
        return str(value)

    def process_result_value(self, value: Any, dialect: Dialect) -> Any:
        if value is None:
            return value
        return UUID(str(value))


class VectorJSON(TypeDecorator):
    """JSON list of floats on SQLite; pgvector on PostgreSQL."""

    impl = JSON
    cache_ok = True

    def __init__(self, dim: int = 1536) -> None:
        super().__init__()
        self.dim = dim

    def load_dialect_impl(self, dialect: Dialect) -> TypeEngine[Any]:
        if dialect.name == "postgresql":
            from pgvector.sqlalchemy import Vector

            return dialect.type_descriptor(Vector(self.dim))
        return dialect.type_descriptor(JSON())

    def process_bind_param(self, value: Any, dialect: Dialect) -> Any:
        if value is None:
            return value
        if dialect.name == "postgresql":
            return value
        if isinstance(value, str):
            return json.loads(value)
        return list(value)

    def process_result_value(self, value: Any, dialect: Dialect) -> Any:
        if value is None:
            return value
        if isinstance(value, str):
            return json.loads(value)
        return list(value)
