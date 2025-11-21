#
# Copyright (c) 2024–2025, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

"""Gemini Live + Twilio/WebRTC + NestJS MCP Booking Example (Unified Version)."""

import asyncio
import os
from dotenv import load_dotenv
from loguru import logger
from datetime import datetime
import pytz
import aiohttp
from typing import Optional, Dict, Any

# Pipecat Imports
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import EndTaskFrame, LLMRunFrame, TranscriptionMessage
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContext
from pipecat.processors.transcript_processor import TranscriptProcessor
from pipecat.processors.frameworks.rtvi import RTVIConfig, RTVIObserver, RTVIProcessor
from pipecat.runner.types import RunnerArguments
from pipecat.runner.utils import parse_telephony_websocket, create_transport
from pipecat.serializers.twilio import TwilioFrameSerializer
from pipecat.services.google.gemini_live.llm import GeminiLiveLLMService
from pipecat.services.llm_service import FunctionCallParams
from pipecat.transports.websocket.fastapi import FastAPIWebsocketTransport, FastAPIWebsocketParams
from pipecat.transports.base_transport import TransportParams
from mcp_client import NestJSMCPClient
from handlers.client_handler import ClientHandlers
from pipecat.serializers.protobuf import ProtobufFrameSerializer

load_dotenv(override=True)



# -------------------------------------------------------
# Gemini + Multi-Transport Bot
# -------------------------------------------------------

async def run_bot(transport, runner_args: RunnerArguments, caller_number: str = "",  context: dict = None):
    logger.info("🚀 Starting Gemini + Multi-Transport booking bot")
    logger.info(f"📱 Caller number: {caller_number or 'Not provided'}")

    # Initialize MCP client
    mcp_client = NestJSMCPClient(
        base_url=os.getenv("MCP_SERVER_URL", "http://localhost:3004/v1"),
        api_key=os.getenv("MCP_API_KEY", ""),
    )

    try:
        health = await mcp_client.health_check()
        logger.info(f"✅ MCP Health: {health}")
    except Exception as e:
        logger.warning(f"⚠️ MCP connection failed: {e}")

    llm = None

    value = "x"
    match value:
        case "client-web":
            print("1")
        case "client-call":
            handlers = ClientHandlers(mcp_client, default_phone=caller_number)

            # get branch information from phone
            # get buisiness information from branch

            # check if phone number is registered from client,
            # if not, create account by asking for 1. first name, last name, country code, phone, whatsapp 
            # use the information to create an account.
            # if account is found, use the reference to make transactions
            print("2")

            # Gemini LLM service
            llm = GeminiLiveLLMService(
                api_key=os.getenv("GOOGLE_API_KEY"),
                model="models/gemini-2.5-flash-native-audio-preview-09-2025",
                voice_id="Aoede", # Puck, Charon, Fenrir,Kore, Aoede
                system_instruction=handlers.get_instructions(),
                tools=handlers.tools
            )

            # Register handlers
            llm.register_function("make_booking", handlers.make_booking)
            llm.register_function("get_bookings", handlers.get_bookings)
            llm.register_function("cancel_bookings", handlers.cancel_bookings)
            llm.register_function("get_services", handlers.get_services)

        case "business":
            print("2")
        case _:
            print("unknown")


    

    # Conversation context
    # messages = [{"role": "user", "content": "Hi Geny, can you help me book a service?"}]
    messages = [
        {
            "role": "user",
            "content": "Please greet the caller with: 'Hi! You've reached Sailing Winds Beauty & Wellness. I'm with a client but Geny can help you book your services.' Then ask how you can help them. the greetings should be in a friendly tone",
        },
    ]
    context = OpenAILLMContext(messages)
    context_aggregator = llm.create_context_aggregator(context)
    context = OpenAILLMContext(messages)
    context_aggregator = llm.create_context_aggregator(context)
    transcript = TranscriptProcessor()
    rtvi = RTVIProcessor(config=RTVIConfig(config=[]))

    # Define the pipeline
    pipeline = Pipeline([
        transport.input(),
        rtvi,
        context_aggregator.user(),
        transcript.user(),
        llm,
        transport.output(),
        transcript.assistant(),
        context_aggregator.assistant(),
    ])

    task = PipelineTask(
        pipeline,
        params=PipelineParams(enable_metrics=True, enable_usage_metrics=True),
        idle_timeout_secs=runner_args.pipeline_idle_timeout_secs,
        observers=[RTVIObserver(rtvi)],
    )

    @transport.event_handler("on_client_connected")
    async def on_connect(transport, client):
        logger.info("📞 Client connected")
        await task.queue_frames([LLMRunFrame()])


    @transport.event_handler("on_client_disconnected")
    async def on_disconnect(transport, client):
        logger.info("👋 Client disconnected")
        await task.cancel()
        await mcp_client.close()

    # @transcript.event_handler("on_transcript_update")
    # async def on_transcript(processor, frame):
    #     for msg in frame.messages:
    #         if isinstance(msg, TranscriptionMessage):
    #             logger.info(f"{msg.role}: {msg.content}")

    @transcript.event_handler("on_transcript_update")
    async def on_transcript(processor, frame):
        for msg in getattr(frame, "messages", []):
            role = getattr(msg, "role", "unknown")
            text = getattr(msg, "text", None) or getattr(msg, "content", None)
            if text:
                print(f"{role}: {text}")

    

    runner = PipelineRunner(handle_sigint=runner_args.handle_sigint)
    try:
        await runner.run(task)
    finally:
        await mcp_client.close()


# -------------------------------------------------------
# Unified Transport Entry Point (Twilio + WebRTC)
# -------------------------------------------------------

import os
import logging
from pipecat.runner.types import RunnerArguments

logger = logging.getLogger(__name__)


async def bot(runner_args: RunnerArguments):
    """Main bot entry point compatible with both Twilio and WebRTC clients."""
    logger.info("🚀 Starting Gemini bot (Twilio/WebRTC support)")

    # ─────────────────────────────
    # Optional noise filter
    # ─────────────────────────────
    krisp_filter = None
    if os.environ.get("ENV") != "local":
        try:
            from pipecat.audio.filters.krisp_filter import KrispFilter
            krisp_filter = KrispFilter()
            logger.info("✅ Krisp noise filter enabled")
        except ImportError:
            logger.warning("⚠️ Krisp filter not available, continuing without it")

    caller_number = ""
    context = {}

    # ─────────────────────────────
    # Try Twilio detection first
    # ─────────────────────────────
    try:
        transport_type, call_data = await parse_telephony_websocket(runner_args.websocket)
        logger.info(f"📞 Detected transport type: {transport_type}")

        if transport_type == "twilio":
            caller_number = call_data.get("body", {}).get("from", "")
            to_number = call_data.get("body", {}).get("to", "")
            logger.info(f"📱 Twilio caller number: {caller_number} → {to_number}")

            serializer = TwilioFrameSerializer(
                stream_sid=call_data["stream_id"],
                call_sid=call_data["call_id"],
                account_sid=os.getenv("TWILIO_ACCOUNT_SID", ""),
                auth_token=os.getenv("TWILIO_AUTH_TOKEN", ""),
            )

            transport = FastAPIWebsocketTransport(
                websocket=runner_args.websocket,
                params=FastAPIWebsocketParams(
                    audio_in_enabled=True,
                    audio_out_enabled=True,
                    add_wav_header=False,
                    audio_in_filter=krisp_filter,
                    vad_analyzer=SileroVADAnalyzer(params=VADParams(stop_secs=0.5)),
                    serializer=serializer,
                ),
            )


            context = {
                "type": "client",
                "channel" : "call",
                "session": "",
                "metadata": {
                    "caller": caller_number,
                    "recipient": to_number,
                    "call_sid": call_data["call_id"],
                    "stream_sid": call_data["stream_id"],
                    "account_sid": os.getenv("TWILIO_ACCOUNT_SID", ""),
                }
            }

            contextx = {
                "type": "customer",
                "channel": "twilio",
                "branch": "123456",
                "language": "en",
                "session": "1234",
                "call_info": {
                    "caller": caller_number,
                    "recipient": to_number,
                    "call_sid": call_data["call_id"],
                    "stream_sid": call_data["stream_id"],
                    "account_sid": os.getenv("TWILIO_ACCOUNT_SID", ""),
                },
            }

            logger.info(f"👤 Twilio context: {context}")
            await run_bot(transport, runner_args, caller_number, context)
            return

    except Exception as e:
        logger.info(f"ℹ️ Not a Twilio connection, falling back to WebRTC: {e}")

    # ─────────────────────────────
    # WebRTC fallback
    # ─────────────────────────────
    try:
        logger.info("🌐 Using WebRTC transport")

        # Manually build transport (since create_transport doesn't accept force_type)
        params = TransportParams(
            audio_in_enabled=True,
            audio_in_filter=krisp_filter,
            audio_out_enabled=True,
            vad_analyzer=SileroVADAnalyzer(params=VADParams(stop_secs=0.5)),
            serializer=ProtobufFrameSerializer(),  # 
        )

        transport = FastAPIWebsocketTransport(
            websocket=runner_args.websocket,
            params=FastAPIWebsocketParams(**params.__dict__)
        )

        context = {
            "branch": "123456",
            "type": "business",
            "channel": "webrtc",
            "language": "en",
            "session": "1234",
        }

        logger.info(f"👤 WebRTC context: {context}")
        await run_bot(transport, runner_args, caller_number="", context=context)

    except Exception as e:
        logger.error(f"❌ Failed to initialize WebRTC transport: {e}", exc_info=True)
        await runner_args.websocket.close()

    finally:
        logger.info("🧹 Bot session ended. Connection closed.")

        
async def bot2(runner_args: RunnerArguments):
    """Main bot entry point compatible with both Twilio and WebRTC."""
    logger.info("🚀 Starting Gemini bot (Twilio/WebRTC support)")

    

    # Optional noise filter
    if os.environ.get("ENV") != "local":
        try:
            from pipecat.audio.filters.krisp_filter import KrispFilter
            krisp_filter = KrispFilter()
            logger.info("✅ Krisp noise filter enabled")
        except ImportError:
            logger.warning("⚠️ Krisp filter not available, continuing without it")
            krisp_filter = None
    else:
        krisp_filter = None

    caller_number = ""

    # Try to detect Twilio transport first
    try:
        transport_type, call_data = await parse_telephony_websocket(runner_args.websocket)
        logger.info(f"📞 Detected transport type: {transport_type}")

        if transport_type == "twilio":
            # Extract caller phone number from Twilio
            caller_number = call_data.get("body", {}).get("from", "")
            to_number = call_data.get("body", {}).get("to", "")
            logger.info(f"📱 Twilio caller number: {caller_number}")

            # Create Twilio-specific serializer
            serializer = TwilioFrameSerializer(
                stream_sid=call_data["stream_id"],
                call_sid=call_data["call_id"],
                account_sid=os.getenv("TWILIO_ACCOUNT_SID", ""),
                auth_token=os.getenv("TWILIO_AUTH_TOKEN", ""),
            )

            transport = FastAPIWebsocketTransport(
                websocket=runner_args.websocket,
                params=FastAPIWebsocketParams(
                    audio_in_enabled=True,
                    audio_out_enabled=True,
                    add_wav_header=False,  # Twilio expects raw PCM16
                    audio_in_filter=krisp_filter,
                    vad_analyzer=SileroVADAnalyzer(params=VADParams(stop_secs=0.5)),
                    serializer=serializer,
                ),
            )

            context={
                "type": "customer",
                "channel": "twilio",
                "branch": "123456",
                "language": "en",
                "session": "1234",
                "call_info" : {
                    "caller" : caller_number,
                    "receipient" : to_number,
                    "call_sid" : call_data["call_id"],
                    "stream_sid" : call_data["stream_id"],
                    "account_sid" : os.getenv("TWILIO_ACCOUNT_SID", "")
                }
            }


            if context:
                logger.info(f"👤 Received user context: {context}")
           
            await run_bot(transport, runner_args, caller_number, context)
            return

    except Exception as e:
        logger.info(f"ℹ️ Not a Twilio connection, trying WebRTC: {e}")

    # If not Twilio, use WebRTC transport
    logger.info("🌐 Using WebRTC transport")
    
    transport_params = {
        "webrtc": lambda: TransportParams(
            audio_in_enabled=True,
            audio_in_filter=krisp_filter,
            audio_out_enabled=True,
            vad_analyzer=SileroVADAnalyzer(params=VADParams(stop_secs=0.5)),
        ),
    }

    transport = await create_transport(runner_args, transport_params)

    context={
        "branch": "123456",
        "type": "business",
        "channel": "webrtc",
        "language": "en",
        "session": "1234",
    }
    print(">>>>>>>>>>>><<<<<<<<<<<<")
    print(context)
    print(">>>>>>>>>>>><<<<<<<<<<<<")
    
    # For WebRTC, caller_number remains empty (will ask user)
    await run_bot(transport, runner_args, caller_number="", context=context)


# -------------------------------------------------------
# Main Entry (for local or Pipecat Cloud)
# -------------------------------------------------------

if __name__ == "__main__":
    from pipecat.runner.run import main
    main()