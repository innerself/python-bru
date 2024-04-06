import enum
import json
from http import HTTPMethod
from pathlib import Path
from typing import Self, Any, Union

from pydantic import BaseModel, Field

from app.common import RequestBodyType, ParamPlacement
from app.openapi.parser import OpenAPIParser
schema_from_rel_path = OpenAPIParser._schema_from_ref

INDENT = ' ' * 2


class RequestAuthType(enum.Enum):
    NONE = 'none'


class EndpointType(enum.Enum):
    HTTP = 'http'
    GRAPHQL = 'graphql'


class AttributeType(enum.Enum):
    INTEGER = 0
    STRING = ''

    @classmethod
    def from_string(cls, value: str) -> Self:
        return cls[value.upper()]

    @classmethod
    def from_enum(cls, value: dict) -> Self:
        # TODO User structural type matching
        if 'type' in value:
            return cls[value['type'].upper()]

        return {
            int: cls.INTEGER,
            str: cls.STRING,
        }[type(value['enum'][0])]


class EndpointConfig(BaseModel):
    http_method: HTTPMethod | None = None
    url: Path | str | None = None
    body_type: RequestBodyType | None = None
    auth_type: RequestAuthType | None = None

    def to_bru(self) -> str:
        return '\n'.join([
            f'{self.http_method.lower()} {{',
            f'{INDENT}url: {{{{host}}}}{self.url}/',
            f'{INDENT}body: {getattr(self.body_type, "value", None)}',
            f'{INDENT}auth: {getattr(self.auth_type, "value", None)}',
            '}',
        ])


class RequestHeaders(BaseModel):
    content_type: str | None = None

    def to_bru(self) -> str:
        if not self.content_type:
            return ''

        return '\n'.join([
            'headers {',
            f'{INDENT}Content-Type: {self.content_type}',
            '}'
        ])


class RequestPayloadItem(BaseModel):
    name: str
    default_value: Any = ''
    required: bool = False
    selected: bool = False
    placement: ParamPlacement | None = None
    item_type: str | dict | None = None

    def to_bru(self) -> str:
        sel = '' if self.selected else '~'
        return f"{sel}{self.name}: {self.default_value or ''}"


class QueryParameter(RequestPayloadItem):
    pass


class BodyProperty(RequestPayloadItem):
    pass


class EndpointVar(RequestPayloadItem):
    pass


class RequestNestedItem(BaseModel):
    name: str
    items: list[Union[RequestPayloadItem, 'RequestNestedItem']] = Field(default_factory=list)


class RequestQuery(BaseModel):
    params: list[QueryParameter] | None = Field(default_factory=list)

    def to_bru(self) -> str:
        if not self.params:
            return ''

        return '\n'.join([
            'query {',
            *[f'{INDENT}{p.to_bru()}' for p in self.params],
            '}'
        ])


class RequestBody(BaseModel):
    body_type: RequestBodyType | None = None
    # content_type: str | None = None
    props: list[BodyProperty | RequestNestedItem] | None = Field(default_factory=list)
    json_data: dict | None = None

    def json_data_from_json_props(self, raw_open_api: dict, schema: dict):
        json_data = {}

        if 'enum' in schema:
            return AttributeType.from_enum(schema).value

        for property_name, property_data in schema['properties'].items():
            if '$ref' in property_data:
                property_data = schema_from_rel_path(
                    raw_open_api, property_data['$ref']
                )
                json_data[property_name] = self.json_data_from_json_props(
                    raw_open_api, property_data
                )
                continue

            json_data[property_name] = property_data.get('default')

        return json_data

    def json_data_from_schema(self, raw_open_api: dict, schema: dict) -> dict:
        if not self.json_data:
            self.json_data = self.json_data_from_json_props(raw_open_api, schema)
        return self.json_data

    def to_bru(self) -> str:
        if not self.props and not self.json_data:
            return ''

        return '\n'.join([
            f'body:{self.body_type.body_block_type(self.body_type)} {{',
            *self._props_to_bru(),
            '}'
        ])

    def _props_to_bru(self):
        if self.body_type == RequestBodyType.JSON:
            json_stub = {}
            for prop in self.props:
                json_stub[prop.name] = self._prop_to_bru(prop)
            json_lines = json.dumps(json_stub, indent=2).splitlines()
            return ['\n'.join([f'{INDENT}{line}' for line in json_lines])]
        else:
            return [f'{INDENT}{p.to_bru()}' for p in self.props]

    def _prop_to_bru(self, prop: BodyProperty | RequestNestedItem):
        if isinstance(prop, BodyProperty):
            return prop.default_value
        elif isinstance(prop, RequestNestedItem):
            return {
                nested_prop.name: self._prop_to_bru(nested_prop)
                for nested_prop in prop.items
            }
        else:
            raise ValueError(f'Unknown property type: {type(prop)}')


class EndpointVars(BaseModel):
    pre_request: list[EndpointVar] | None = Field(default_factory=list)
    post_request: list[EndpointVar] | None = Field(default_factory=list)

    def to_bru(self):
        parts = []

        if self.pre_request:
            parts.append('\n'.join([
                'vars:pre-request {',
                *[f'{INDENT}{v.to_bru()}' for v in self.pre_request],
                '}'
            ]))

        if self.post_request:
            parts.append('\n'.join([
                'vars:post-request {',
                *[f'{INDENT}{v.to_bru()}' for v in self.post_request],
                '}'
            ]))

        return '\n'.join(parts)


class EndpointMeta(BaseModel):
    endpoint_name: str | None = None
    endpoint_type: EndpointType | None = None
    sequence: int | None = None

    def to_bru(self) -> str:
        return '\n'.join([
            'meta {',
            f'{INDENT}name: {self.endpoint_name}',
            f'{INDENT}type: {self.endpoint_type.value}',
            f'{INDENT}seq: {self.sequence}',
            '}'
        ])


class EndpointDocs(BaseModel):
    description: str | None = None

    def to_bru(self) -> str:
        if not self.description:
            return ''

        return '\n'.join([
            'docs {',
            f'{INDENT}{self.description}',
            '}'
        ])


class BrunoEndpoint(BaseModel):
    meta: EndpointMeta | None = None
    config: EndpointConfig | None = None
    headers: RequestHeaders | None = None
    body: RequestBody | None = None
    query: RequestQuery | None = None
    vars: EndpointVars | None = None
    docs: EndpointDocs | None = None

    def to_bru(self) -> str:
        return '\n\n'.join([
            part.to_bru() for part
            in self._blocks_order()
            if part and part.to_bru()
        ]) + '\n'

    def _blocks_order(self) -> tuple:
        return (
            self.meta,
            self.config,
            self.headers,
            self.query,
            self.body,
            self.vars,
            self.docs,
        )


RequestNestedItem.update_forward_refs()
