"""Tiny FastAPI wrapper exposing the demo agent over HTTP.

POST /run {"input": "..."} -> {"text": "...", "meta": {"agent": "demo"}}
200 on success, 400 on missing "input".

Run standalone with: uvicorn examples.stub_endpoint:app --port 8001
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from examples.demo_agent import create_agent

app = FastAPI()
_agent = create_agent()


@app.post("/run")
async def run(request: Request):
    body = await request.json()
    input_ = body.get("input")
    if input_ is None:
        return JSONResponse({"error": "missing 'input'"}, status_code=400)
    text = _agent(input_)
    return {"text": text, "meta": {"agent": "demo"}}
