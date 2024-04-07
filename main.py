import argparse
import asyncio
import json
import pathlib
from pathlib import Path

import aiofiles
import httpx

from app.openapi.coupler import OpenAPICoupler
from app.openapi.parser import OpenAPIParser


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


async def main(file_path: str, api_dir: pathlib.Path) -> None:
    api_dir.mkdir(exist_ok=True, parents=True)

    if '://' not in file_path:
        file_path = Path(file_path)

    raw_open_api = await get_raw_openapi(file_path)
    api_parser = OpenAPIParser(raw_open_api)
    api_data = api_parser.parse()

    coupler = OpenAPICoupler(api_data, api_dir)
    await coupler.couple()


if __name__ == "__main__":
    cli_parser = argparse.ArgumentParser()
    cli_parser.add_argument('-f', '--file_path', type=str, help='Path to file')
    cli_parser.add_argument('-d', '--api_dir', type=pathlib.Path, help='Path to API dir')

    args = cli_parser.parse_args()

    asyncio.run(main(
        file_path=args.file_path,
        api_dir=args.api_dir,
    ))
