import enum
from typing import Self


class RequestBodyType(enum.Enum):
    NONE = None
    JSON = 'json'
    FORM_URL_ENCODED = 'formUrlEncoded'

    @classmethod
    def from_content_type(cls, content_type: str | None) -> Self:
        # TODO USE STRUCTURAL TYPE MATCHING!!!
        if content_type is None:
            return None
        if content_type == 'application/x-www-form-urlencoded':
            return cls.FORM_URL_ENCODED
        return cls.JSON

    def body_block_type(self, request_type: Self) -> str:
        return {
            self.NONE: self.NONE.value,
            self.JSON: self.JSON.value,
            self.FORM_URL_ENCODED: 'form-urlencoded',
        }[request_type]


class ParamPlacement(enum.Enum):
    PATH = 'path'
    QUERY = 'query'
    HEADER = 'header'
