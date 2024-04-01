import asyncio
import enum
import json
from pathlib import Path
from textwrap import dedent
from typing import Any, Self
from pprint import pformat

import aiofiles
from loguru import logger
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).parent
APIS_DIR = BASE_DIR / 'apis'
BRU_FILE_SUFFIX = '.bru'
INDENT = ' ' * 2

NO_ROOT = slice(1, None)


class HTTPMethod(enum.Enum):
    GET = 'get'
    POST = 'post'
    PUT = 'put'
    PATCH = 'patch'
    DELETE = 'delete'


class RequestBodyType(enum.Enum):
    NONE = 'none'
    JSON = 'json'
    FORM_URL_ENCODED = 'formUrlEncoded'

    @classmethod
    def from_content_type(cls, content_type: str | None) -> Self:
        # TODO USE STRUCTURAL TYPE MATCHING!!!
        if content_type is None:
            return cls.NONE
        if content_type == 'application/x-www-form-urlencoded':
            return cls.FORM_URL_ENCODED
        return cls.JSON

    def body_block_type(self, request_type: Self) -> str:
        return {
            self.NONE: self.NONE.value,
            self.JSON: self.JSON.value,
            self.FORM_URL_ENCODED: 'form-urlencoded',
        }[request_type]


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
    url: str | None = None
    body_type: RequestBodyType | None = RequestBodyType.NONE
    auth_type: RequestAuthType | None = RequestAuthType.NONE

    def to_bru(self) -> str:
        return '\n'.join([
            f'{self.http_method.value} {{',
            f'{INDENT}url: {{{{host}}}}{self.url.removesuffix("/")}/',
            f'{INDENT}body: {self.body_type.value}',
            f'{INDENT}auth: {self.auth_type.value}',
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
    item_type: str | dict | None = None

    def to_bru(self) -> str:
        sel = '' if self.selected else '~'
        return f"{sel}{self.name}: {self.default_value or ''}"


class QueryParameter(RequestPayloadItem):
    pass


class BodyProperty(RequestPayloadItem):
    pass


class RequestNestedItem(BaseModel):
    item: RequestPayloadItem


class RequestQuery(BaseModel):
    params: list[QueryParameter] | None = Field(default_factory=list)

    def params_from_json(self, params: dict) -> list[QueryParameter]:
        print()

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
    props: list[BodyProperty] | None = Field(default_factory=list)
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
            json_lines = json.dumps(self.json_data, indent=2).splitlines()
            return ['\n'.join([f'{INDENT}{line}' for line in json_lines])]
        else:
            return [f'{INDENT}{p.to_bru()}' for p in self.props]


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


class RequestDocs(BaseModel):
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
    docs: RequestDocs | None = None

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
            self.docs,
        )


def body_props_from_schema(raw_open_api, schema):
    props = []
    for property_name, property_data in schema['properties'].items():
        if '$ref' in property_data:
            property_data = schema_from_rel_path(
                raw_open_api, property_data['$ref']
            )['properties']
        props.append(BodyProperty(
            name=property_name,
            default_value=property_data['default'],
            item_type=property_data['type'],
            required=(property_name in schema['required']),
            selected=(property_name in schema['required']),
        ))
    props.sort(key=lambda p: (int(p.required) * -1, p.name))
    return props


def schema_from_rel_path(raw_open_api: dict, rel_path: str) -> dict:
    request_schema_path_items = rel_path.removeprefix('#/').split('/')
    schema = raw_open_api
    while len(request_schema_path_items) > 0:
        schema = schema.get(request_schema_path_items.pop(0))
    return schema


async def main():
    # open_api_file = BASE_DIR / 'template_ping.json'
    # open_api_file = BASE_DIR / 'template_get_person_list.json'
    # open_api_file = BASE_DIR / 'template_auth_login.json'
    # open_api_file = BASE_DIR / 'template_event_storage_events.json'
    open_api_file = BASE_DIR / 'swagger.json'
    async with aiofiles.open(open_api_file) as f:
        raw_open_api = json.loads(await f.read())

    api_name = raw_open_api['info']['title']
    APIS_DIR.mkdir(exist_ok=True)
    api_root_folder = APIS_DIR / api_name
    api_root_folder.mkdir(exist_ok=True)

    sequence_number = 0
    for ep_path, ep_data in raw_open_api['paths'].items():
        path = Path(ep_path)
        endpoint_dir = api_root_folder.joinpath(*path.parts[NO_ROOT])
        endpoint_dir.mkdir(parents=True, exist_ok=True)

        for method_name, method_data in ep_data.items():
            http_method = HTTPMethod(method_name)
            sequence_number += 1
            method_file = endpoint_dir.joinpath(method_name).with_suffix(BRU_FILE_SUFFIX)

            endpoint_meta = EndpointMeta(
                endpoint_name=path.parts[-1],
                endpoint_type=EndpointType.HTTP,
                sequence=sequence_number,
            )
            endpoint_config = EndpointConfig(
                http_method=http_method,
                url=str(path),
            )
            request_docs = RequestDocs(description=method_data['summary'])
            endpoint = BrunoEndpoint(
                meta=endpoint_meta,
                config=endpoint_config,
                docs=request_docs,
            )
            endpoint.headers = RequestHeaders()

            if http_method is HTTPMethod.GET:
                endpoint.query = RequestQuery()

                for raw_param in method_data.get('parameters', []):
                    if not any(raw_param['schema']):
                        continue

                    endpoint.query.params.append(QueryParameter(
                        name=raw_param.get('name'),
                        default_value=raw_param['schema'].get('default'),
                        required=raw_param['required'],
                        item_type=raw_param['schema'].get('type'),
                    ))
                    endpoint.query.params.sort(key=lambda p: (int(p.required) * -1, p.name))

            elif http_method is HTTPMethod.POST:
                request_body = method_data.get('requestBody', {})
                content = request_body.get('content')
                if not content:
                    continue
                content_type = list(content.keys())[0]
                endpoint.headers.content_type = content_type
                endpoint.config.body_type = RequestBodyType.from_content_type(content_type)
                schema_type = content[content_type]['schema'].get('type')
                if schema_type == 'array':
                    request_schema_path = content[content_type]['schema']['items']['$ref']
                else:
                    request_schema_path = content[content_type]['schema']['$ref']
                schema = schema_from_rel_path(raw_open_api, request_schema_path)
                endpoint.body = RequestBody(
                    body_type=RequestBodyType.from_content_type(
                        endpoint.headers.content_type
                    )
                )
                if endpoint.body.body_type is RequestBodyType.JSON:
                    endpoint.body.json_data_from_schema(raw_open_api, schema)
                    if schema_type == 'array':
                        endpoint.body.json_data = [endpoint.body.json_data]
            elif http_method is HTTPMethod.DELETE:
                request_body = method_data.get('requestBody', {})
                content = request_body.get('content')
                if not content:
                    continue
                content_type = list(content.keys())[0]
                endpoint.headers.content_type = content_type
                endpoint.config.body_type = RequestBodyType.from_content_type(content_type)
                request_schema_path = content[content_type]['schema']['$ref']
                schema = schema_from_rel_path(raw_open_api, request_schema_path)

                endpoint.body = RequestBody(
                    body_type=RequestBodyType.from_content_type(
                        endpoint.headers.content_type
                    )
                )
                if endpoint.body.body_type is RequestBodyType.JSON:
                    endpoint.body.json_data_from_schema(raw_open_api, schema)
            else:
                print()

            async with aiofiles.open(method_file, 'w') as f:
                await f.write(endpoint.to_bru())


if __name__ == "__main__":
    asyncio.run(main())
