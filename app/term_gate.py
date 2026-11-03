"""Path gate in front of ttyd.

Form routes (/key-box, /nara-key-box, /set-key, /set-nara-key) go to the
companion on 8767. Everything else, including ttyd websockets, goes to ttyd
on 8081. Listens on 127.0.0.1:8080, which is what term.itjd.com hits.
"""
from __future__ import annotations

import asyncio
import sys

LISTEN_HOST = "127.0.0.1"
LISTEN_PORT = 8080
FORM_PORT = 8767
TTYD_PORT = 8081
FORM_PATHS = (
    b"/nara-key-box",
    b"/set-nara-key",
    b"/key-box",
    b"/set-key",
    b"/modal-token-box",
    b"/set-modal-token",
)


def _is_form(head: bytes) -> bool:
    line = head.split(b"\r\n", 1)[0]
    parts = line.split(b" ")
    if len(parts) < 2:
        return False
    path = parts[1].split(b"?", 1)[0]
    return any(path == p or path.startswith(p + b"/") or path.startswith(p + b"?") for p in FORM_PATHS)


async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while True:
            data = await reader.read(65536)
            if not data:
                break
            writer.write(data)
            await writer.drain()
    except (ConnectionResetError, BrokenPipeError, asyncio.CancelledError):
        pass
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


async def _handle(
    client_reader: asyncio.StreamReader, client_writer: asyncio.StreamWriter
) -> None:
    try:
        head = await client_reader.readexactly(1)
        extra = await client_reader.read(4095)
        head += extra
        port = FORM_PORT if _is_form(head) else TTYD_PORT
        target_reader, target_writer = await asyncio.open_connection(LISTEN_HOST, port)
        target_writer.write(head)
        await target_writer.drain()
        await asyncio.gather(
            _pipe(client_reader, target_writer),
            _pipe(target_reader, client_writer),
        )
    except (asyncio.IncompleteReadError, ConnectionRefusedError, OSError):
        try:
            client_writer.close()
            await client_writer.wait_closed()
        except Exception:
            pass


async def _main() -> None:
    server = await asyncio.start_server(_handle, LISTEN_HOST, LISTEN_PORT)
    async with server:
        await server.serve_forever()


def main() -> None:
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
