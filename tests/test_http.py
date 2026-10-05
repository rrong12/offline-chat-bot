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


async def test_get_json_parses_json_sent_as_text_and_sends_headers():
    seen = {}

    async def plain(request):
        seen["accept"] = request.headers.get("Accept")
        return web.Response(text='{"joke": "ha"}', content_type="text/plain")

    server = await serve(plain)
    client = HttpClient(timeout=1)
    try:
        url = str(server.make_url("/"))
        assert await client.get_json(url, headers={"Accept": "application/json"}) == {"joke": "ha"}
        assert seen["accept"] == "application/json"
    finally:
        await client.close()
        await server.close()


async def test_get_json_reads_a_body_sent_in_pieces():
    async def chunked(request):
        resp = web.StreamResponse(headers={"Content-Type": "application/json"})
        await resp.prepare(request)
        await resp.write(b'{"fact": "cats ')
        await asyncio.sleep(0.02)
        await resp.write(b'purr"}')
        await resp.write_eof()
        return resp

    server = await serve(chunked)
    client = HttpClient(timeout=1)
    try:
        assert await client.get_json(str(server.make_url("/"))) == {"fact": "cats purr"}
    finally:
        await client.close()
        await server.close()


async def test_get_json_refuses_oversized_bodies(monkeypatch):
    import bot.http

    monkeypatch.setattr(bot.http, "MAX_BODY", 10)

    async def big(request):
        return web.json_response({"fact": "x" * 100})

    server = await serve(big)
    client = HttpClient(timeout=1)
    try:
        assert await client.get_json(str(server.make_url("/"))) is None
    finally:
        await client.close()
        await server.close()


async def test_get_json_returns_none_for_non_json_200():
    async def html(request):
        return web.Response(text="<html>challenge</html>", content_type="text/html")

    server = await serve(html)
    client = HttpClient(timeout=1)
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
