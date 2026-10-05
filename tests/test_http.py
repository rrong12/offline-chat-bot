import asyncio

from aiohttp import web
from aiohttp.test_utils import TestServer

from bot.http import HttpClient


async def serve(handler) -> TestServer:
    app = web.Application()
    app.router.add_get("/", handler)
    server = TestServer(app)
    await server.start_server()
    return server


async def test_get_json_returns_parsed_body():
    async def ok(request):
        assert request.headers["User-Agent"].startswith("offline-chat-bot")
        return web.json_response({"fact": "cats sleep a lot"})

    server = await serve(ok)
    client = HttpClient(timeout=1)
    try:
        assert await client.get_json(str(server.make_url("/"))) == {"fact": "cats sleep a lot"}
    finally:
        await client.close()
        await server.close()


async def test_get_json_returns_none_on_timeout():
    async def slow(request):
        await asyncio.sleep(1)
        return web.json_response({})

    server = await serve(slow)
    client = HttpClient(timeout=0.2)
    try:
        assert await client.get_json(str(server.make_url("/"))) is None
    finally:
        await client.close()
        await server.close()


async def test_get_json_returns_none_on_http_error():
    async def broken(request):
        return web.Response(status=500)

    server = await serve(broken)
    client = HttpClient(timeout=1)
    try:
        assert await client.get_json(str(server.make_url("/"))) is None
    finally:
        await client.close()
        await server.close()
