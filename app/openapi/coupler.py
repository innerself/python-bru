from pathlib import Path

import aiofiles

from app.bruno import parts as bru_parts
from app.common import RequestBodyType, ParamPlacement
from app.openapi.parts import API as OpenAPI, Endpoint as OpenAPIEndpoint, Parameter as OpenAPIParameter, \
    NestedObject as OpenAPINestedObject


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
        match self._get_request_body_type(endpoint):
            case RequestBodyType.JSON as body_type:
                props = self._couple_body_json(endpoint)
            case None as body_type:
                props = None
            case body_type:
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
