import asyncio
import json
from http import HTTPMethod
from pathlib import Path

import aiofiles

from app.bruno.parts import EndpointType, EndpointConfig, RequestHeaders, \
    QueryParameter, EndpointVar, RequestQuery, RequestBody, EndpointVars, EndpointMeta, EndpointDocs, \
    BrunoEndpoint
from app.common import RequestBodyType, ParamPlacement
from app.openapi.parser import OpenAPIParser
from app.openapi.parts import (
    API as OpenAPI,
    Endpoint as OpenAPIEndpoint,
    NestedObject as OpenAPINestedObject,
    Parameter as OpenAPIParameter,
)
from app.bruno import parts as bru_parts


parse_path_param = OpenAPIParser._parse_path_param
schema_from_rel_path = OpenAPIParser._schema_from_ref

BASE_DIR = Path(__file__).parent
APIS_DIR = BASE_DIR / 'apis'
BRU_FILE_SUFFIX = '.bru'

NO_ROOT = slice(1, None)


def dup_fig_par(string: str) -> str:
    return string.replace('{', '{{').replace('}', '}}')


async def get_raw_openapi(file_path: Path) -> dict:
    if file_path.is_file():
        async with aiofiles.open(file_path) as f:
            return json.loads(await f.read())
    else:
        print()


def make_dirs(apis_dir: Path, api_name: str) -> Path:
    apis_dir.mkdir(exist_ok=True)
    api_root_folder = APIS_DIR / api_name
    api_root_folder.mkdir(exist_ok=True)

    return api_root_folder


class OpenAPICoupler:
    _BRU_FILE_SUFFIX = '.bru'

    def __init__(self, api_data: OpenAPI, root_folder: Path):
        self._api_data = api_data
        self._root_folder = root_folder
        self._sequence_number: int = 0

    async def couple(self):
        for _, openapi_path in self._api_data.paths.items():
            self._make_path_dirs(openapi_path.path)

            for oa_endpoint in openapi_path.endpoints:
                self._sequence_number += 1
                method_filename = self._get_method_filename(oa_endpoint)
                bru_endpoint = self._couple_endpoint(oa_endpoint)
                await self.write_to_file(bru_endpoint, method_filename)

    def _couple_endpoint(self, endpoint: OpenAPIEndpoint):
        return bru_parts.BrunoEndpoint(
            meta=self._couple_meta(endpoint),
            config=self._couple_config(endpoint),
            headers=self._couple_headers(endpoint),
            body=self._couple_body(endpoint),
            query=self._couple_query(endpoint),
            vars=self._couple_vars(endpoint),
            docs=self._couple_docs(endpoint),
        )

    def _couple_meta(self, endpoint: OpenAPIEndpoint):
        return bru_parts.EndpointMeta(
            endpoint_name=endpoint.path.stem,
            endpoint_type=bru_parts.EndpointType.HTTP,
            sequence=self._sequence_number,
        )

    def _couple_config(self, endpoint: OpenAPIEndpoint):
        return bru_parts.EndpointConfig(
            http_method=endpoint.method,
            url=endpoint.path,
            body_type=self._get_body_content_type(endpoint),
        )

    def _couple_headers(self, endpoint: OpenAPIEndpoint):
        return bru_parts.RequestHeaders(
            content_type=self._get_body_content_type(endpoint),
        )

    def _couple_body(self, endpoint: OpenAPIEndpoint):
        # TODO Use structural type matching!!!
        body_type = self._get_request_body_type(endpoint)
        if body_type == RequestBodyType.JSON:
            props = self._couple_body_json(endpoint)
        elif not body_type:
            props = None
        else:
            raise ValueError(f'Unsupported body type: {body_type}')

        return bru_parts.RequestBody(
            body_type=body_type,
            props=props,
        )

    def _couple_query(self, endpoint: OpenAPIEndpoint):
        return bru_parts.RequestQuery(
            params=[
                self._couple_payload_item(parameter)
                for parameter in getattr(endpoint.query, 'parameters', [])
                if parameter.placement is ParamPlacement.QUERY
            ]
        )

    def _couple_vars(self, endpoint: OpenAPIEndpoint):
        return bru_parts.EndpointVars(
            pre_request=[
                self._couple_payload_item(parameter)
                for parameter in getattr(endpoint.query, 'parameters', [])
                if parameter.placement is ParamPlacement.PATH
            ]
        )

    def _couple_docs(self, endpoint: OpenAPIEndpoint):
        return bru_parts.EndpointDocs(
            description=endpoint.description,
        )

    def _couple_body_json(self, endpoint: OpenAPIEndpoint):
        return [
            self._couple_payload_item(parameter)
            for parameter in getattr(endpoint.body, 'payload', [])
        ]

    def _couple_payload_item(self, item: OpenAPIParameter | OpenAPINestedObject):
        if isinstance(item, OpenAPINestedObject):
            return bru_parts.RequestNestedItem(
                name=item.name,
                items=[
                    self._couple_payload_item(nested_param)
                    for nested_param in item.parameters
                ])

        param_class = self._get_param_class(item.placement)
        return param_class(
            name=item.name,
            default_value=item.default,
            required=item.required,
            selected=item.required,
            placement=item.placement,
            item_type=item.type_,
        )

    @staticmethod
    def _get_body_content_type(endpoint: OpenAPIEndpoint):
        return getattr(endpoint.body, 'content_type', None)

    def _get_request_body_type(self, endpoint: OpenAPIEndpoint):
        return bru_parts.RequestBodyType.from_content_type(
            self._get_body_content_type(endpoint)
        )

    @staticmethod
    def _get_param_class(placement: ParamPlacement | None):
        return {
            None: bru_parts.BodyProperty,
            ParamPlacement.PATH: bru_parts.EndpointVar,
            ParamPlacement.QUERY: bru_parts.QueryParameter,
            ParamPlacement.HEADER: '',
        }[placement]

    def _make_path_dirs(self, path: Path):
        path_dir = self._root_folder / path.relative_to('/')
        path_dir.mkdir(parents=True, exist_ok=True)

    def _get_method_filename(self, endpoint: OpenAPIEndpoint):
        return self._root_folder.joinpath(
            endpoint.path.relative_to('/'), endpoint.method.lower()
        ).with_suffix(self._BRU_FILE_SUFFIX)

    @staticmethod
    async def write_to_file(endpoint: bru_parts.BrunoEndpoint, file_path: Path):
        async with aiofiles.open(file_path, 'w') as f:
            await f.write(endpoint.to_bru())


async def main():
    open_api_file = BASE_DIR / 'swagger.json'
    raw_open_api = await get_raw_openapi(open_api_file)

    parser = OpenAPIParser(raw_open_api)
    api_data = parser.parse()
    api_root_folder = make_dirs(APIS_DIR, 'box-dev')

    coupler = OpenAPICoupler(api_data, api_root_folder)
    await coupler.couple()

    print('Done')

    sequence_number = 0
    for _, openapi_path in api_data.paths.items():
        path_dir = api_root_folder / openapi_path.path.relative_to('/')
        path_dir.mkdir(parents=True, exist_ok=True)

        for oa_endpoint in openapi_path.endpoints:
            sequence_number += 1

            body_content_type = getattr(oa_endpoint.body, 'content_type', None)
            bru_endpoint = bru_parts.BrunoEndpoint()
            bru_endpoint.meta = bru_parts.EndpointMeta(
                endpoint_name=openapi_path.path.stem,
                endpoint_type=bru_parts.EndpointType.HTTP,
                sequence=sequence_number,
            )
            bru_endpoint.config = bru_parts.EndpointConfig(
                http_method=oa_endpoint.method,
                url=openapi_path.path,
                body_type=body_content_type,
            )
            bru_endpoint.headers = bru_parts.RequestHeaders(
                content_type=body_content_type,
            )
            from app.openapi.parts import NestedObject
            for p in getattr(oa_endpoint.body, 'payload', []):
                if isinstance(p, NestedObject):
                    print()



            bru_endpoint.body = bru_parts.RequestBody(
                body_type=bru_parts.RequestBodyType.from_content_type(body_content_type),
                props=[
                    bru_parts.BodyProperty(
                        name=p.name,
                        default_value=p.default,
                        required=p.required,
                        item_type=p.type_,
                    ) for p in getattr(oa_endpoint.body, 'payload', [])
                ],
            )
            bru_endpoint.query = bru_parts.RequestQuery(
                params=[
                    bru_parts.QueryParameter(
                        name=p.name,
                        default_value=p.default,
                        required=p.required,
                        selected=p.required,
                        placement=p.placement,
                        item_type=p.type_,
                    ) for p in getattr(oa_endpoint.query, 'parameters', [])
                    if p.placement is ParamPlacement.QUERY
                ],
            )
            bru_endpoint.vars = bru_parts.EndpointVars(
                pre_request=[
                    bru_parts.EndpointVar(
                        name=p.name,
                        default_value=p.default,
                        required=p.required,
                        selected=p.required,
                        placement=p.placement,
                        item_type=p.type_,
                    ) for p in getattr(oa_endpoint.query, 'parameters', [])
                    if p.placement is ParamPlacement.PATH
                ],
            )
            bru_endpoint.docs = bru_parts.EndpointDocs(
                description=oa_endpoint.description,
            )

            method_file = path_dir.joinpath(
                oa_endpoint.method.lower()
            ).with_suffix(BRU_FILE_SUFFIX)
            async with aiofiles.open(method_file, 'w') as f:
                await f.write(bru_endpoint.to_bru())

    # for ep_path, ep_data in raw_open_api['paths'].items():
    #     path = Path(ep_path)
    #     endpoint_dir = api_root_folder.joinpath(*[dup_fig_par(p) for p in path.parts[NO_ROOT]])
    #     endpoint_dir.mkdir(parents=True, exist_ok=True)
    #
    #     for method_name, method_data in ep_data.items():
    #         http_method = HTTPMethod(method_name)
    #         sequence_number += 1
    #         method_file = endpoint_dir.joinpath(method_name).with_suffix(BRU_FILE_SUFFIX)
    #
    #         endpoint_meta = EndpointMeta(
    #             endpoint_name=dup_fig_par(path.name),
    #             endpoint_type=EndpointType.HTTP,
    #             sequence=sequence_number,
    #         )
    #         endpoint_config = EndpointConfig(
    #             http_method=http_method,
    #             url=str(path),
    #         )
    #         request_docs = EndpointDocs(description=method_data['summary'])
    #         endpoint = BrunoEndpoint(
    #             meta=endpoint_meta,
    #             config=endpoint_config,
    #             docs=request_docs,
    #         )
    #         endpoint.headers = RequestHeaders()
    #
    #         if http_method is HTTPMethod.GET:
    #             endpoint.query = RequestQuery()
    #
    #             for raw_param in method_data.get('parameters', []):
    #                 if not any(raw_param['schema']):
    #                     continue
    #
    #                 if path_param := parse_path_param(raw_param):
    #                     endpoint.config.url = dup_fig_par(endpoint.config.url)
    #                     var = EndpointVar(
    #                         name=path_param.name,
    #                         required=True,
    #                         selected=True,
    #                     )
    #                     if not endpoint.vars:
    #                         endpoint.vars = EndpointVars()
    #                     endpoint.vars.pre_request.append(var)
    #                     continue
    #
    #                 endpoint.query.params.append(QueryParameter(
    #                     name=raw_param.get('name'),
    #                     default_value=raw_param['schema'].get('default'),
    #                     required=raw_param['required'],
    #                     item_type=raw_param['schema'].get('type'),
    #                 ))
    #                 endpoint.query.params.sort(key=lambda p: (int(p.required) * -1, p.name))
    #
    #         elif http_method is HTTPMethod.POST:
    #             request_body = method_data.get('requestBody', {})
    #             content = request_body.get('content')
    #             if not content:
    #                 continue
    #             content_type = list(content.keys())[0]
    #             endpoint.headers.content_type = content_type
    #             endpoint.config.body_type = RequestBodyType.from_content_type(content_type)
    #             schema_type = content[content_type]['schema'].get('type')
    #             if schema_type == 'array':
    #                 request_schema_path = content[content_type]['schema']['items']['$ref']
    #             else:
    #                 request_schema_path = content[content_type]['schema']['$ref']
    #             schema = schema_from_rel_path(raw_open_api, request_schema_path)
    #             endpoint.body = RequestBody(
    #                 body_type=RequestBodyType.from_content_type(
    #                     endpoint.headers.content_type
    #                 )
    #             )
    #             if endpoint.body.body_type is RequestBodyType.JSON:
    #                 endpoint.body.json_data_from_schema(raw_open_api, schema)
    #                 if schema_type == 'array':
    #                     endpoint.body.json_data = [endpoint.body.json_data]
    #         elif http_method is HTTPMethod.PUT:
    #             for raw_param in method_data.get('parameters', []):
    #                 if not any(raw_param['schema']):
    #                     continue
    #
    #                 if path_param := parse_path_param(raw_param):
    #                     endpoint.config.url = dup_fig_par(endpoint.config.url)
    #                     var = EndpointVar(
    #                         name=path_param.name,
    #                         required=True,
    #                         selected=True,
    #                     )
    #                     if not endpoint.vars:
    #                         endpoint.vars = EndpointVars()
    #                     endpoint.vars.pre_request.append(var)
    #
    #             request_body = method_data.get('requestBody', {})
    #             content = request_body.get('content')
    #             if content:
    #                 content_type = list(content.keys())[0]
    #                 endpoint.headers.content_type = content_type
    #                 endpoint.config.body_type = RequestBodyType.from_content_type(content_type)
    #                 request_schema_path = content[content_type]['schema']['$ref']
    #                 schema = schema_from_rel_path(raw_open_api, request_schema_path)
    #
    #                 endpoint.body = RequestBody(
    #                     body_type=RequestBodyType.from_content_type(
    #                         endpoint.headers.content_type
    #                     )
    #                 )
    #                 if endpoint.body.body_type is RequestBodyType.JSON:
    #                     endpoint.body.json_data_from_schema(raw_open_api, schema)
    #         elif http_method is HTTPMethod.DELETE:
    #             for raw_param in method_data.get('parameters', []):
    #                 if not any(raw_param['schema']):
    #                     continue
    #
    #                 if path_param := parse_path_param(raw_param):
    #                     endpoint.config.url = dup_fig_par(endpoint.config.url)
    #                     var = EndpointVar(
    #                         name=path_param.name,
    #                         required=True,
    #                         selected=True,
    #                     )
    #                     if not endpoint.vars:
    #                         endpoint.vars = EndpointVars()
    #                     endpoint.vars.pre_request.append(var)
    #
    #             request_body = method_data.get('requestBody', {})
    #             content = request_body.get('content')
    #             if content:
    #                 content_type = list(content.keys())[0]
    #                 endpoint.headers.content_type = content_type
    #                 endpoint.config.body_type = RequestBodyType.from_content_type(content_type)
    #                 request_schema_path = content[content_type]['schema']['$ref']
    #                 schema = schema_from_rel_path(raw_open_api, request_schema_path)
    #
    #                 endpoint.body = RequestBody(
    #                     body_type=RequestBodyType.from_content_type(
    #                         endpoint.headers.content_type
    #                     )
    #                 )
    #                 if endpoint.body.body_type is RequestBodyType.JSON:
    #                     endpoint.body.json_data_from_schema(raw_open_api, schema)
    #
    #         async with aiofiles.open(method_file, 'w') as f:
    #             await f.write(endpoint.to_bru())


if __name__ == "__main__":
    asyncio.run(main())
