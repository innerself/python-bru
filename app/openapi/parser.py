import pathlib
from typing import Callable

from http import HTTPMethod

import app.common
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
            parsed_path = parts.Path(path=pathlib.Path(path))
            for method_name, method_data in methods.items():
                parser = self._method_parser(HTTPMethod(method_name.upper()))
                parsed_path.endpoints.append(parser(path, method_data))
            self.parsed_api.paths[path] = parsed_path
        return self.parsed_api

    def _method_parser(self, method: HTTPMethod) -> Callable:
        return {
            HTTPMethod.GET: self._parse_get,
            HTTPMethod.POST: self._parse_post,
            HTTPMethod.PUT: self._parse_put,
            HTTPMethod.DELETE: self._parse_delete,
        }[method]

    def _body_parser(self, type_: RequestBodyType) -> Callable | None:
        return {
            RequestBodyType.NONE: None,
            RequestBodyType.JSON: self._parse_body_json,
            RequestBodyType.FORM_URL_ENCODED: self._parse_body_form_url_encoded,
        }[type_]

    def _parse_get(self, path: str, data: dict) -> parts.Endpoint:
        endpoint = parts.Endpoint(
            path=pathlib.Path(path),
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
            path=pathlib.Path(path),
            method=HTTPMethod.POST,
            description=data.get('summary') or data('description'),
        )

        if parameters := [
            self._parse_parameter(parameter_data)
            for parameter_data in data.get('parameters', [])
        ]:
            endpoint.query = parts.Query(parameters=parameters)

        if raw_body := data.get('requestBody'):
            endpoint.body = self._parse_body(raw_body)

        return endpoint

    def _parse_put(self, path: str, data: dict) -> parts.Endpoint:
        endpoint = parts.Endpoint(
            path=pathlib.Path(path),
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

    def _parse_delete(self, path: str, data: dict) -> parts.Endpoint:
        endpoint = parts.Endpoint(
            path=pathlib.Path(path),
            method=HTTPMethod.DELETE,
            description=data.get('summary') or data('description'),
        )

        if parameters := [
            self._parse_parameter(parameter_data)
            for parameter_data in data.get('parameters', [])
        ]:
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
            schema = self._schema_from_ref(schema_data['items']['$ref'])
        else:
            schema = self._schema_from_ref(schema_data['$ref'])

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
                    required=(property_name in data.get('required', [])),
                    default=property_data.get('default'),
                ))
            else:
                if all_of := property_data.get('allOf'):
                    schema = self._schema_from_ref(all_of[0]['$ref'])
                    if 'enum' in schema:
                        body.payload.append(self._parse_enum(
                            name=property_name,
                            data=property_data,
                        ))
                    else:
                        nested_body = self._parse_body_json(schema)
                        nested_object = parts.NestedObject(
                            name=property_name,
                            parameters=nested_body.payload,
                        )
                        body.payload.append(nested_object)
                else:
                    if ref := property_data.get('$ref'):
                        schema = self._schema_from_ref(ref)
                        if 'enum' in schema:
                            body.payload.append(self._parse_enum(
                                name=property_name,
                                data=property_data,
                            ))
                        else:
                            nested_body = self._parse_body_json(schema)
                            nested_object = parts.NestedObject(
                                name=property_name,
                                parameters=nested_body.payload,
                            )
                            body.payload.append(nested_object)
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
            schema = self._schema_from_ref(all_of[0]['$ref'])
            if 'enum' in schema:
                parameter = self._parse_enum(
                    name=data['name'],
                    data=data,
                )
            else:
                print()
        else:
            placement = app.common.ParamPlacement(data['in'])
            if placement is app.common.ParamPlacement.PATH:
                parameter = self._parse_path_param(data)
            elif placement is app.common.ParamPlacement.QUERY:
                parameter = self._parse_query_param(data)
            elif placement is app.common.ParamPlacement.HEADER:
                parameter = self._parse_header_param(data)
            else:
                print()

        return parameter

    def _parse_query_param(self, data: dict) -> parts.Parameter:
        schema = data['schema']
        if '$ref' in data['schema']:
            schema = self._schema_from_ref(data['schema']['$ref'])
            if 'enum' in schema:
                return self._parse_enum(name=data['name'], data=data)

        param = self._parse_param_common(data)
        param.placement = app.common.ParamPlacement.QUERY
        param.default = schema.get('default')
        return param

    def _parse_path_param(self, data: dict) -> parts.Parameter:
        param = self._parse_param_common(data)
        param.placement = app.common.ParamPlacement.PATH
        return param

    def _parse_header_param(self, data: dict) -> parts.Parameter:
        param = self._parse_param_common(data)
        param.placement = app.common.ParamPlacement.HEADER
        return param

    @staticmethod
    def _parse_param_common(data: dict) -> parts.Parameter:
        return parts.Parameter(
            name=data['name'],
            type_=data['schema']['type'],
            required=data['required'],
        )

    def _parse_enum(self, name: str, data: dict) -> parts.Parameter:
        return parts.Parameter(
            name=name,
            type_='enum',
            placement=app.common.ParamPlacement(data.get('in')) if data.get('in') else None,
            required=data.get('required', False),
            default=data.get('default'),
        )

    def _schema_from_ref(self, rel_path: str) -> dict:
        path = pathlib.Path(rel_path.removeprefix('#/'))
        schema = self._raw_schema
        for part in path.parts:
            schema = schema.get(part)
        return schema

    @staticmethod
    def dup_fig_par(string: str) -> str:
        return string.replace('{', '{{').replace('}', '}}')

