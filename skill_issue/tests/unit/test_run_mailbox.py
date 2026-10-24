"""The public health server answers 200 ok and reveals nothing about the agent."""

import asyncio

from scripts.run_mailbox import _health


async def test_health_server_answers_ok_for_any_path():
    server = await asyncio.start_server(_health, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    for path in ("/health", "/connect", "/agent_info"):
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(f"GET {path} HTTP/1.1\r\nHost: x\r\n\r\n".encode())
        await writer.drain()
        response = await reader.read()
        writer.close()
        assert response.startswith(b"HTTP/1.1 200 OK") and response.endswith(b"\r\n\r\nok")
    server.close()
    await server.wait_closed()
