import pathlib
from typing import Callable

from http import HTTPMethod

from app.common import RequestBodyType
from app.openapi import parts


class OpenAPIParser:
    def __init__(self, schema: dict):
        self._raw_schema = schema
        self.api_name = schema['info']['title']
        self.parsed_api = parts.API()

    def parse(self):
        for path, methods in self._raw_schema['paths'].items():
            if '{' in path:
                path = self.dup_fig_par(path)
            # TODO Remove
            if 'ping' in path or 'config' in path:
                continue
            parsed_path = parts.Path(path=pathlib.Path(path))
            for method_name, method_data in methods.items():
                parser = self._method_parser(HTTPMethod(method_name.upper()))
                parsed_path.endpoints.append(parser(path, method_data))
            self.parsed_api.paths[path] = parsed_path

    def _method_parser(self, method: HTTPMethod) -> Callable:
        return {
            HTTPMethod.GET: self._parse_get,
            HTTPMethod.POST: self._parse_post,
            HTTPMethod.PUT: self._parse_put,
        }[method]

    def _body_parser(self, type_: RequestBodyType) -> Callable | None:
        return {
            RequestBodyType.NONE: None,
            RequestBodyType.JSON: self._parse_body_json,
            RequestBodyType.FORM_URL_ENCODED: self._parse_body_form_url_encoded,
        }[type_]

    def _parse_get(self, path: str, data: dict) -> parts.Endpoint:
        endpoint = parts.Endpoint(
            method=HTTPMethod.GET,
            description=data.get('summary') or data('description'),
        )

        parameters = [
            self._parse_parameter(parameter_data)
            for parameter_data in data.get('parameters', [])
        ]

        if parameters:
            endpoint.query = parts.Query(parameters=parameters)

        return endpoint

    def _parse_post(self, path: str, data: dict) -> parts.Endpoint:
        endpoint = parts.Endpoint(
            method=HTTPMethod.POST,
            description=data.get('summary') or data('description'),
        )

        if raw_body := data.get('requestBody'):
            endpoint.body = self._parse_body(raw_body)
        else:
            print()

        return endpoint

    def _parse_put(self, path: str, data: dict) -> parts.Endpoint:
        endpoint = parts.Endpoint(
            method=HTTPMethod.PUT,
            description=data.get('summary') or data('description'),
        )

        parameters = [
            self._parse_parameter(parameter_data)
            for parameter_data in data.get('parameters', [])
        ]

        if parameters:
            endpoint.query = parts.Query(parameters=parameters)

        if raw_body := data.get('requestBody'):
            endpoint.body = self._parse_body(raw_body)

        return endpoint

    def _parse_body(self, data: dict) -> parts.Body:
        content_type = list(data['content'])[0]
        body_type = RequestBodyType.from_content_type(content_type)
        schema_data = data['content'][content_type]['schema']
        schema_type = schema_data.get('type')
        if schema_type == 'array':
            schema = self.schema_from_rel_path(schema_data['items']['$ref'])
        else:
            schema = self.schema_from_rel_path(schema_data['$ref'])

        if parser := self._body_parser(body_type):
            body = parser(schema)
        else:
            print()

        return body

    def _parse_body_json(self, data: dict) -> parts.Body:
        body = parts.Body(content_type=RequestBodyType.JSON)
        for property_name, property_data in data['properties'].items():
            if 'type' in property_data:
                body.payload.append(parts.Parameter(
                    name=property_name,
                    type_=property_data['type'],
                    required=(property_name in data['required']),
                    default=property_data.get('default'),
                ))
            else:
                if all_of := property_data.get('allOf'):
                    schema = self.schema_from_rel_path(all_of[0]['$ref'])
                    if 'enum' in schema:
                        body.payload.append(self._parse_enum(
                            name=property_name,
                            data=property_data,
                        ))
                    else:
                        print()
                else:
                    print()

        return body

    def _parse_body_form_url_encoded(self, data: dict) -> parts.Body:
        body = parts.Body(content_type=RequestBodyType.FORM_URL_ENCODED)
        for property_name, property_data in data['properties'].items():
            body.payload.append(parts.Parameter(
                name=property_name,
                type_=property_data['type'],
                required=(property_name in data['required']),
            ))

        return body

    def _parse_parameter(self, data: dict) -> parts.Parameter:
        if all_of := data['schema'].get('allOf'):
            schema = self.schema_from_rel_path(all_of[0]['$ref'])
            if 'enum' in schema:
                parameter = self._parse_enum(
                    name=data['name'],
                    data=data,
                )
            else:
                print()
        else:
            placement = parts.Placement(data['in'])
            if placement is parts.Placement.PATH:
                parameter = self._parse_path_param(data)
            elif placement is parts.Placement.QUERY:
                parameter = self._parse_query_param(data)
            else:
                print()

        return parameter

    def _parse_query_param(self, data: dict) -> parts.Parameter:
        return parts.Parameter(
            name=data['name'],
            type_=data['schema']['type'],
            placement=parts.Placement.QUERY,
            required=data['required'],
            default=data['schema'].get('default'),
        )

    def _parse_path_param(self, data: dict) -> parts.Parameter:
        return parts.Parameter(
            name=data['name'],
            type_=data['schema']['type'],
            placement=parts.Placement.PATH,
            required=data['required'],
        )

    def _parse_enum(self, name: str, data: dict) -> parts.Parameter:
        return parts.Parameter(
            name=name,
            type_='enum',
            placement=parts.Placement(data.get('in')) if data.get('in') else None,
            required=data.get('required', False),
            default=data.get('default'),
        )


    # def parse_request_body(self, method_data: dict) -> Body | None:
    #     if content := method_data.get('requestBody', {}).get('content'):
    #         content_type = list(content.keys())[0]
    #         request_schema_path = content[content_type]['schema']['$ref']
    #         schema = schema_from_rel_path(raw_open_api, request_schema_path)
    #
    #         endpoint.body = RequestBody(
    #             body_type=RequestBodyType.from_content_type(
    #                 endpoint.headers.content_type
    #             )
    #         )
    #         if endpoint.body.body_type is RequestBodyType.JSON:
    #             endpoint.body.json_data_from_schema(raw_open_api, schema)
    #
    #     return None

    def schema_from_rel_path(self, rel_path: str) -> dict:
        # TODO Try pathlib.Path
        path_items = rel_path.removeprefix('#/').split('/')
        schema = self._raw_schema
        while path_items:
            schema = schema.get(path_items.pop(0))
        return schema

    @staticmethod
    def dup_fig_par(string: str) -> str:
        return string.replace('{', '{{').replace('}', '}}')

