import enum
import pathlib
from typing import Any

from pydantic import BaseModel, Field

from http import HTTPMethod

from app.common import RequestBodyType


class Placement(enum.Enum):
    PATH = 'path'
    QUERY = 'query'


class Parameter(BaseModel):
    name: str
    type_: str
    placement: Placement | None = None
    required: bool
    default: Any = None


class Query(BaseModel):
    parameters: list[Parameter] = Field(default_factory=list)


class Body(BaseModel):
    content_type: RequestBodyType
    payload: list[Parameter] = Field(default_factory=list)


class Endpoint(BaseModel):
    # path: Path
    method: HTTPMethod
    query: Query | None = None
    body: Body | None = None
    description: str | None = None


class Path(BaseModel):
    path: pathlib.Path
    endpoints: list[Endpoint] = Field(default_factory=list)


class API(BaseModel):
    paths: dict[str, Path] | None = Field(default_factory=dict)
