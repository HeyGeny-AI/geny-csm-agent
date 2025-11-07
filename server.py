#
# Copyright (c) 2025, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

import argparse
import os
from typing import Any, Dict

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import HTMLResponse
from twilio.twiml.voice_response import Connect, Stream, VoiceResponse
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from fastapi import FastAPI, WebSocket
from pipecat.runner.types import WebSocketRunnerArguments
from pipecat.transports.websocket.fastapi import (
    FastAPIWebsocketTransport,
    FastAPIWebsocketParams,
)
from bot import run_bot

# Load environment variables from .env file
load_dotenv()

# In-memory store for body data by call SID
call_body_data = {}

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for testing
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_websocket_url(host: str) -> str:
    """Get the appropriate WebSocket URL based on environment."""
    env = os.getenv("ENV", "local").lower()

    if env == "production":
        return "wss://api.pipecat.daily.co/ws/twilio"
    else:
        return f"wss://{host}/ws"


def generate_twiml(host: str, body_data: dict = None) -> str:
    """Generate TwiML response with WebSocket streaming using Twilio SDK."""
    # websocket_url = get_websocket_url("fa0bbb762607.ngrok-free.app")
    websocket_url = get_websocket_url(host)

    # Create TwiML response
    response = VoiceResponse()
    connect = Connect()
    stream = Stream(url=websocket_url)

    # Add Pipecat Cloud service host for production
    env = os.getenv("ENV", "local").lower()
    if env == "production":
        agent_name = os.getenv("AGENT_NAME")
        org_name = os.getenv("ORGANIZATION_NAME")
        service_host = f"{agent_name}.{org_name}"
        stream.parameter(name="_pipecatCloudServiceHost", value=service_host)

    # Add body parameter (if provided)
    if body_data:
        # Pass each key-value pair as separate parameters instead of JSON string
        for key, value in body_data.items():
            stream.parameter(name=key, value=value)

    connect.append(stream)
    response.append(connect)
    response.pause(length=20)

    return str(response)


@app.post("/")
async def start_call(request: Request):
    """Handle Twilio webhook and return TwiML with WebSocket streaming."""
    print("POST TwiML")

    # Parse form data from Twilio webhook
    form_data = await request.form()

    # Extract call information
    call_sid = form_data.get("CallSid", "")
    from_number = form_data.get("From", "")
    to_number = form_data.get("To", "")

    # Extract body data from query parameters and add phone numbers
    body_data = {}
    for key, value in request.query_params.items():
        body_data[key] = value

    # Always include phone numbers in body data
    body_data["from"] = from_number
    body_data["to"] = to_number

    # Log call details
    if call_sid:
        print(f"Twilio inbound call SID: {call_sid}")
        if body_data:
            print(f"Body data: {body_data}")

    # Validate environment configuration for production
    env = os.getenv("ENV", "local").lower()
    if env == "production":
        if not os.getenv("AGENT_NAME") or not os.getenv("ORGANIZATION_NAME"):
            raise HTTPException(
                status_code=500,
                detail="AGENT_NAME and ORGANIZATION_NAME must be set for production deployment",
            )

    # Get request host and construct WebSocket URL
    host = request.headers.get("host")
    if not host:
        raise HTTPException(status_code=400, detail="Unable to determine server host")

    # Generate TwiML response (body_data always contains phone numbers)
    twiml_content = generate_twiml(host, body_data)

    return HTMLResponse(content=twiml_content, media_type="application/xml")

@app.websocket("/ws")
async def twilio_websocket_endpoint(websocket: WebSocket):
    print("💡 Twilio attempting WebSocket connection...")
    await websocket.accept()
    print("✅ Twilio WebSocket connection accepted for inbound call")

    try:
        from bot import bot
        from pipecat.runner.types import WebSocketRunnerArguments

        runner_args = WebSocketRunnerArguments(websocket=websocket)
        runner_args.handle_sigint = False

        await bot(runner_args)

    except Exception as e:
        import traceback
        print("❌ ERROR in WebSocket endpoint:\n", traceback.format_exc())
        await websocket.close()


@app.post("/connect")
async def bot_connect(request: Request) -> Dict[Any, Any]:
    server_mode = os.getenv("WEBSOCKET_SERVER", "fast_api")
    if server_mode == "websocket_server":
        # ws_url = "ws://localhost:8765"
        ws_url = "wss://pipecat.server.heygeny.com"
        
    else:
        # ws_url = "ws://localhost:7860/ws-browser"
        ws_url = "wss://pipecat.server.heygeny.com/ws-browser"
    return {"ws_url": ws_url}


from pipecat.serializers.protobuf import ProtobufFrameSerializer



@app.websocket("/ws-browser")
async def websocket_browser(websocket: WebSocket):

    print("💡 Browser attempting WebSocket connection...")
    print(f"Headers: {websocket.headers}")
    print(f"Query params: {dict(websocket.query_params)}")
    
    # Add these lines before accept
    origin = websocket.headers.get("origin", "")
    print(f"Origin: {origin}")

     # Extract query parameters
    query_params = dict(websocket.query_params)
    branch = query_params.get("branch", "")
    session = query_params.get("session", "")
    
    print(f"📱 Browser connection params:")
    print(f"   branch: {branch}")
    print(f"   Session ID: {session}")


    await websocket.accept()
    print("✅ WebSocket connection accepted for browser client")

    try:
        runner_args = WebSocketRunnerArguments(websocket=websocket)
        runner_args.handle_sigint = False

        # Create Pipecat transport for browser audio
        transport = FastAPIWebsocketTransport(
            websocket=websocket,
            params=FastAPIWebsocketParams(
                audio_in_enabled=True,
                audio_out_enabled=True,
            ),
        )

        # Create FastAPI transport for Pipecat
        transport = FastAPIWebsocketTransport(
            websocket=websocket,
            params=FastAPIWebsocketParams(
                audio_in_enabled=True,
                audio_out_enabled=True,
                add_wav_header=False,
                vad_analyzer=SileroVADAnalyzer(),
                serializer=ProtobufFrameSerializer(),
            ),
        )

        await run_bot(
            transport=transport,
            runner_args=runner_args,
            caller_number="browser-user",
            context={
                "branch": branch,
                "type": "business",
                "channel": "webrtc",
                # "phone": "",
                "language": "en",
                "session": session,
            }
        )

    except Exception as e:
        import traceback
        print("❌ ERROR in browser WebSocket endpoint:\n", traceback.format_exc())
        await websocket.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pipecat Twilio Chatbot Server")
    parser.add_argument(
        "-t", "--test", action="store_true", default=False, help="set the server in testing mode"
    )
    args, _ = parser.parse_known_args()

    app.state.testing = args.test

    uvicorn.run(app, host="0.0.0.0", port=7860)