"""Loopback typed research page. Spark stays closed without MODEL_API_KEY."""

from __future__ import annotations

import os
from typing import Literal
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from urllib.parse import urlsplit
from pydantic import BaseModel, Field

from app.envfile import load_env, write_key
from app.modal_toml import modal_token_present, parse_modal_pair, write_modal_token
from app.nara_keyfile import nara_key_present, write_nara_key
from app.law_gateway import DEFAULT_MCP_URL
from app.muse_client import CreditNotReady, spark_ready

load_env()
from app.muse_params import KEYWORDS, REASONING_EFFORT, SPARK_MODEL, VOICE_MODEL
from app.preflight import preflight
from app.research import DISCLAIMER, research
from app.spend import spend_status
from app.voice_client import transcribe_file, transcript_text

WEB = Path(__file__).resolve().parent.parent / "web"
app = FastAPI(title="Open Indiana Research", docs_url=None, redoc_url=None)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=[
    '127.0.0.1', 'localhost', '[::1]', 'term.itjd.com', 'testserver',
])


@app.middleware('http')
async def reject_cross_origin_writes(request: Request, call_next):
    if request.method not in {'GET', 'HEAD', 'OPTIONS'}:
        origin = request.headers.get('origin')
        # Origin is supplied by browsers on form/JSON POSTs. Native local
        # clients may omit it; Host protection still applies to those clients.
        if (request.headers.get('sec-fetch-site') == 'cross-site'
                or (origin is not None and (
                    origin == 'null' or urlsplit(origin).netloc != request.headers.get('host')
                    or urlsplit(origin).scheme not in {'http', 'https'}))):
            return HTMLResponse('Cross-origin write refused.', status_code=403)
    return await call_next(request)

app.mount("/static", StaticFiles(directory=WEB), name="static")


class ResearchIn(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    as_of: str | None = None
    mode: Literal["auto", "fixture", "spark", "rehearsal"] = "auto"


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(WEB / "index.html")


@app.get("/title")
async def title_card() -> FileResponse:
    return FileResponse(WEB / "title.html")


@app.get("/captions.vtt")
async def captions() -> FileResponse:
    return FileResponse(WEB / "captions.vtt", media_type="text/vtt")


@app.get("/end")
async def end_card() -> FileResponse:
    return FileResponse(WEB / "end.html")


@app.get("/warmup")
async def warmup() -> dict[str, object]:
    url = os.environ.get("INDIANA_MCP_URL", DEFAULT_MCP_URL)
    report = await preflight(url)
    return report


@app.get("/set-key", response_class=HTMLResponse)
async def get_set_key() -> FileResponse:
    return FileResponse(WEB / "set-key.html")


@app.get("/key-box", response_class=HTMLResponse)
async def get_key_box() -> FileResponse:
    return FileResponse(WEB / "set-key.html")


@app.get("/nara-key-box", response_class=HTMLResponse)
async def get_nara_key_box() -> FileResponse:
    return FileResponse(WEB / "nara-key.html")


@app.get("/modal-token-box", response_class=HTMLResponse)
async def get_modal_token_box() -> FileResponse:
    return FileResponse(WEB / "modal-token.html")


@app.post("/set-modal-token", response_class=HTMLResponse)
async def post_modal_token(
    token_id: str = Form(""),
    token_secret: str = Form(""),
    blob: str = Form(""),
) -> HTMLResponse:
    tid = (token_id or "").strip()
    secret = (token_secret or "").strip()
    if not (tid and secret):
        try:
            tid, secret = parse_modal_pair(blob)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        write_modal_token(tid, secret)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    present = "true" if modal_token_present() else "false"
    return HTMLResponse(
        "<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<title>Modal token saved</title></head><body>"
        "<p>Saved on this Mac. Token not shown.</p>"
        f"<p>modal_token_present: {present}</p>"
        "<p>Reply <strong>key is in</strong> in the Cursor chat.</p>"
        "</body></html>"
    )


@app.post("/set-nara-key", response_class=HTMLResponse)
async def post_nara_key(
    key: str = Form(""),
    keyfile: UploadFile | None = File(None),
) -> HTMLResponse:
    secret = (key or "").strip()
    if not secret and keyfile is not None and keyfile.filename:
        blob = await keyfile.read()
        secret = blob.decode("utf-8", errors="replace").strip()
        if secret.lower().startswith("nara_catalog_api_key="):
            secret = secret.split("=", 1)[1].strip().strip("'").strip('"')
    try:
        write_nara_key(secret)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    present = "true" if nara_key_present() else "false"
    return HTMLResponse(
        "<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<title>NARA key saved</title></head><body>"
        "<p>Saved on this Mac. Key not shown.</p>"
        f"<p>nara_key_present: {present}</p>"
        "<p>Reply <strong>key is in</strong> in the Cursor chat.</p>"
        "</body></html>"
    )


@app.post("/set-key", response_class=HTMLResponse)
async def post_set_key(
    key: str = Form(""),
    keyfile: UploadFile | None = File(None),
) -> HTMLResponse:
    secret = (key or "").strip()
    if not secret and keyfile is not None and keyfile.filename:
        blob = await keyfile.read()
        secret = blob.decode("utf-8", errors="replace").strip()
        if secret.startswith("MODEL_API_KEY="):
            secret = secret.split("=", 1)[1].strip().strip("'").strip('"')
    try:
        write_key(secret)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    ready = "true" if spark_ready() else "false"
    return HTMLResponse(
        "<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<title>Key saved</title></head><body>"
        "<p>Saved on this Mac. Key not shown.</p>"
        f"<p>spark_ready: {ready}</p>"
        "<p>Reply <strong>key is in</strong> in the Cursor chat.</p>"
        "</body></html>"
    )


@app.get("/health")
async def health() -> dict[str, object]:
    return {
        "ok": True,
        "spark_ready": spark_ready() and not spend_status()["spark_closed"],
        "key_present": spark_ready(),
        "modal_token_present": modal_token_present(),
        "mcp_url": os.environ.get("INDIANA_MCP_URL", DEFAULT_MCP_URL),
        "disclaimer": DISCLAIMER,
        "bind": "127.0.0.1",
        "voice_transcribe": False,
        "spark_model": SPARK_MODEL,
        "voice_model": VOICE_MODEL,
        "reasoning_effort": REASONING_EFFORT,
        "voice_keywords": KEYWORDS,
        "spend": spend_status(),
    }


@app.post("/transcribe")
async def post_transcribe(audio: UploadFile = File(...)) -> dict[str, object]:
    if not spark_ready():
        raise HTTPException(
            status_code=409,
            detail="MODEL_API_KEY is unset. Muse Transcribe stays closed.",
        )
    blob = await audio.read()
    if not blob:
        raise HTTPException(status_code=400, detail="Empty audio.")
    try:
        payload = await transcribe_file(
            blob,
            filename=audio.filename or "clip.webm",
            content_type=audio.content_type or "application/octet-stream",
        )
    except CreditNotReady as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "transcript": transcript_text(payload),
        "editable": True,
        "keys_in_response": False,
    }


@app.post("/research")
async def post_research(body: ResearchIn) -> dict[str, object]:
    url = os.environ.get("INDIANA_MCP_URL", DEFAULT_MCP_URL)
    try:
        if body.mode == "rehearsal":
            from app.eviction_demo import rehearse_eviction
            result = await rehearse_eviction(body.question, url=url)
        else:
            result = await research(body.question, as_of=body.as_of, mode=body.mode, url=url)
    except CreditNotReady as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    payload = result.to_dict()
    payload["keys_in_response"] = False
    return payload


def main() -> None:
    import uvicorn

    uvicorn.run("app.server:app", host="127.0.0.1", port=8767, reload=False)


if __name__ == "__main__":
    main()
