import asyncio
import json
from pathlib import Path

import aiofiles

from app.bruno.endpoint_parts import EndpointType, EndpointConfig, RequestHeaders, \
    QueryParameter, BodyProperty, EndpointVar, RequestQuery, RequestBody, EndpointVars, EndpointMeta, EndpointDocs, \
    BrunoEndpoint
from app.common import HTTPMethod, RequestBodyType
from app.openapi.parser import OpenAPIParser
parse_path_param = OpenAPIParser._parse_path_param
schema_from_rel_path = OpenAPIParser.schema_from_rel_path

BASE_DIR = Path(__file__).parent
APIS_DIR = BASE_DIR / 'apis'
BRU_FILE_SUFFIX = '.bru'

NO_ROOT = slice(1, None)


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


def dup_fig_par(string: str) -> str:
    return string.replace('{', '{{').replace('}', '}}')


async def main():
    open_api_file = BASE_DIR / 'swagger.json'
    async with aiofiles.open(open_api_file) as f:
        raw_open_api = json.loads(await f.read())

    parser = OpenAPIParser(raw_open_api)
    api_data = parser.parse()

    APIS_DIR.mkdir(exist_ok=True)
    api_root_folder = APIS_DIR / parser.api_name
    api_root_folder.mkdir(exist_ok=True)

    sequence_number = 0
    for ep_path, ep_data in raw_open_api['paths'].items():
        path = Path(ep_path)
        endpoint_dir = api_root_folder.joinpath(*[dup_fig_par(p) for p in path.parts[NO_ROOT]])
        endpoint_dir.mkdir(parents=True, exist_ok=True)

        for method_name, method_data in ep_data.items():
            http_method = HTTPMethod(method_name)
            sequence_number += 1
            method_file = endpoint_dir.joinpath(method_name).with_suffix(BRU_FILE_SUFFIX)

            endpoint_meta = EndpointMeta(
                endpoint_name=dup_fig_par(path.name),
                endpoint_type=EndpointType.HTTP,
                sequence=sequence_number,
            )
            endpoint_config = EndpointConfig(
                http_method=http_method,
                url=str(path),
            )
            request_docs = EndpointDocs(description=method_data['summary'])
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

                    if path_param := parse_path_param(raw_param):
                        endpoint.config.url = dup_fig_par(endpoint.config.url)
                        var = EndpointVar(
                            name=path_param.name,
                            required=True,
                            selected=True,
                        )
                        if not endpoint.vars:
                            endpoint.vars = EndpointVars()
                        endpoint.vars.pre_request.append(var)
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
            elif http_method is HTTPMethod.PUT:
                for raw_param in method_data.get('parameters', []):
                    if not any(raw_param['schema']):
                        continue

                    if path_param := parse_path_param(raw_param):
                        endpoint.config.url = dup_fig_par(endpoint.config.url)
                        var = EndpointVar(
                            name=path_param.name,
                            required=True,
                            selected=True,
                        )
                        if not endpoint.vars:
                            endpoint.vars = EndpointVars()
                        endpoint.vars.pre_request.append(var)

                request_body = method_data.get('requestBody', {})
                content = request_body.get('content')
                if content:
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
            elif http_method is HTTPMethod.DELETE:
                for raw_param in method_data.get('parameters', []):
                    if not any(raw_param['schema']):
                        continue

                    if path_param := parse_path_param(raw_param):
                        endpoint.config.url = dup_fig_par(endpoint.config.url)
                        var = EndpointVar(
                            name=path_param.name,
                            required=True,
                            selected=True,
                        )
                        if not endpoint.vars:
                            endpoint.vars = EndpointVars()
                        endpoint.vars.pre_request.append(var)

                request_body = method_data.get('requestBody', {})
                content = request_body.get('content')
                if content:
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

            async with aiofiles.open(method_file, 'w') as f:
                await f.write(endpoint.to_bru())


if __name__ == "__main__":
    asyncio.run(main())
