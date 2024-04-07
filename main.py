import asyncio
import json
from pathlib import Path

import aiofiles
import httpx

from app.openapi.coupler import OpenAPICoupler
from app.openapi.parser import OpenAPIParser

BASE_DIR = Path(__file__).parent
APIS_DIR = BASE_DIR / 'apis'


async def get_raw_openapi(file_path: Path | str) -> dict:
    if isinstance(file_path, Path) and file_path.is_file():
        async with aiofiles.open(file_path) as f:
            return json.loads(await f.read())
    elif isinstance(file_path, str) and '://' in file_path:
        async with httpx.AsyncClient() as client:
            response = await client.get(file_path)
            return json.loads(response.text)
    else:
        raise ValueError(f'Unsupported file path type: {file_path}')


def make_dirs(apis_dir: Path, api_name: str) -> Path:
    apis_dir.mkdir(exist_ok=True)
    api_root_folder = APIS_DIR / api_name
    api_root_folder.mkdir(exist_ok=True)

    return api_root_folder


async def main():
    open_api_file = BASE_DIR / 'swagger.json'
    raw_open_api = await get_raw_openapi(open_api_file)

    parser = OpenAPIParser(raw_open_api)
    api_data = parser.parse()
    api_root_folder = make_dirs(APIS_DIR, 'box-dev')

    coupler = OpenAPICoupler(api_data, api_root_folder)
    await coupler.couple()


if __name__ == "__main__":
    asyncio.run(main())
