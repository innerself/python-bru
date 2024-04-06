import pathlib
from typing import Any, Union

from pydantic import BaseModel, Field

from http import HTTPMethod

from app.common import RequestBodyType, ParamPlacement


class Parameter(BaseModel):
    name: str
    type_: str
    placement: ParamPlacement | None = None
    required: bool
    default: Any = None


class NestedObject(BaseModel):
    name: str
    parameters: list[Union[Parameter, 'NestedObject']] = Field(default_factory=list)


class Query(BaseModel):
    parameters: list[Parameter] = Field(default_factory=list)


class Body(BaseModel):
    content_type: RequestBodyType
    payload: list[Parameter | NestedObject] = Field(default_factory=list)


class Endpoint(BaseModel):
    path: pathlib.Path
    method: HTTPMethod
    query: Query | None = None
    body: Body | None = None
    description: str | None = None


class Path(BaseModel):
    path: pathlib.Path
    endpoints: list[Endpoint] = Field(default_factory=list)


class API(BaseModel):
    paths: dict[str, Path] | None = Field(default_factory=dict)


NestedObject.update_forward_refs()
