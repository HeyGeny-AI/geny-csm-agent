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
async def run_bot(transport, runner_args: RunnerArguments, meta: dict = None):
    logger.info("🚀 Starting Gemini + Multi-Transport booking bot")

    # Initialize MCP client
    mcp_client = NestJSMCPClient(
        base_url=os.getenv("MCP_SERVER_URL", "http://localhost:3004/v1"),
        token=os.getenv("MCP_API_KEY", ""),
    )

    try:
        health = await mcp_client.health_check()
        logger.info(f"✅ MCP Health: {health}")
    except Exception as e:
        logger.warning(f"⚠️ MCP connection failed: {e}")

    # Initialize Gemini LLM
    llm = GeminiLiveLLMService(
        api_key=os.getenv("GOOGLE_API_KEY"),
        model="models/gemini-2.5-flash-native-audio-preview-09-2025",
        voice_id="Aoede",
        system_instruction="",
        tools=[]
    )

    messages = []
    handlers = ClientHandlers(mcp_client, meta=meta)
    print(">>>>>>>>>>> 1")
    # ============================================
    # CLIENT CALL HANDLING
    # ============================================
    if meta['type'] == "client":
        print(">>>>>>>>>>> 2")
        # Fetch business by phone
        branch = await handlers.fetch_business_by_phone(meta['metadata']['recipient'])
        business_name = branch['business']['name']
        branch_reference = branch['branch']['reference']
        meta["branch_reference"] = branch_reference

        print(">>>>>>>>>>> 3")

        # Check if client is already registered
        caller_phone = meta['metadata']['caller']
        client = await handlers.mcp_client.get_client_by_phone(caller_phone)
        client_data = client.get("content", {}).get("data", {})
        
        if client_data:
            meta["is_client_registered"] = True
            meta["client"] = client_data
            handlers.meta["client"] = client_data
            handlers.meta["is_client_registered"] = True
        else:
            meta["is_client_registered"] = False
            handlers.meta["is_client_registered"] = False

        print(">>>>>>>>>>> 4")
        # Build initial LLM message
        messages = [
            {
                "role": "user",
                "content": (
                    f"Please greet the caller with: 'Hi! You have reached {business_name}. "
                    "I'm with a client but Geny can help you book your services.' "
                    "Then ask how you can help them. The greeting should be in a friendly tone."
                ),
            }
        ]

        print(">>>>>>>>>>> 5")

        llm._system_instruction = handlers.get_client_instructions()
        llm._tools = handlers.client_tools
        
        # Register client functions
        llm.register_function("make_client_booking", handlers.make_client_booking)
        llm.register_function("get_client_bookings", handlers.get_client_bookings)
        llm.register_function("cancel_booking", handlers.cancel_booking)
        llm.register_function("update_booking", handlers.update_booking)
        llm.register_function("get_services", handlers.get_services)
        llm.register_function("get_business_by_phone", handlers.get_business_by_phone)
        llm.register_function("register_client", handlers.register_client)
        llm.register_function("get_availability_branch", handlers.get_availability_branch)

    # ============================================
    # BUSINESS CALL HANDLING (FIXED)
    # ============================================
    elif meta['type'] == "business":
        # Get branch reference from meta (WebRTC uses meta['branch'])
        branch_reference = meta.get('metadata').get('branch')
        
        if not branch_reference:
            logger.error("❌ No branch reference provided for business call")
            return

        # Fetch branch details
        try:
            response = await handlers.mcp_client.get_branch_by_reference(branch_reference)
            branch = response.get("content", {}).get("data", {})
            
            if not branch:
                logger.error(f"❌ Invalid branch reference: {branch_reference}")
                meta["is_branch_valid"] = False
                messages = [
                    {
                        "role": "user",
                        "content": "The branch provided is invalid. Please check and try again."
                    }
                ]
            else:
                meta["is_branch_valid"] = True
                meta["branch"] = branch
                meta["business"] = branch.get("business", {})
                
                business_name = meta["business"].get("name", "your business")
                
                logger.info(f"✅ Branch validated: {branch.get('name')} - {business_name}")
                
                # Build greeting message
                messages = [
                    {
                        "role": "user",
                        "content": (
                            f"'Hi, Connected to {business_name}.'"
                            "Hit me with your request "
                        ),
                    }
                ]

        except Exception as e:
            logger.error(f"❌ Failed to fetch branch: {e}")
            meta["is_branch_valid"] = False
            messages = [
                {
                    "role": "user",
                    "content": "Unable to connect to the branch system. Please try again later."
                }
            ]

        # Set business instructions and tools
        llm._system_instruction = handlers.get_business_instructions()
        llm._tools = handlers.business_tools


        print(handlers.get_business_instructions())
        
        # Register business functions
        llm.register_function("make_branch_booking", handlers.make_branch_booking)
        llm.register_function("get_branch_bookings", handlers.get_branch_bookings)
        llm.register_function("cancel_booking", handlers.cancel_booking)
        llm.register_function("update_booking", handlers.update_booking)
        llm.register_function("get_availability_branch", handlers.get_availability_branch)
        # Add more business functions as needed:
        # llm.register_function("create_walkin_booking", handlers.create_walkin_booking)

    # ============================================
    # PIPELINE SETUP (Common for both)
    # ============================================
    context = OpenAILLMContext(messages)
    context_aggregator = llm.create_context_aggregator(context)
    transcript = TranscriptProcessor()
    rtvi = RTVIProcessor(config=RTVIConfig(config=[]))

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

    # ─────────────────────────────
    # Try Twilio detection first
    # ─────────────────────────────
    try:
        transport_type, call_data = await parse_telephony_websocket(runner_args.websocket)
        logger.info(f"📞 Detected transport type: {transport_type}")
        
        if transport_type == "twilio":
            logger.info("📱 Building Twilio transport...")
            caller_number = call_data.get("body", {}).get("from", "")
            to_number = call_data.get("body", {}).get("to", "")
            logger.info(f"📞 Call: {caller_number} → {to_number}")
            
            serializer = TwilioFrameSerializer(
                stream_sid=call_data["stream_id"],
                call_sid=call_data["call_id"],
                account_sid=os.getenv("TWILIO_ACCOUNT_SID", ""),
                auth_token=os.getenv("TWILIO_AUTH_TOKEN", ""),
            )
            logger.info("✅ Serializer created")

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
            logger.info("✅ Transport created")

            meta = {
                "type": "client",
                "channel": "call",
                "session": "",
                "language": "en",
                "metadata": {
                    "caller": caller_number,
                    "recipient": to_number,
                    "call_sid": call_data["call_id"],
                    "stream_sid": call_data["stream_id"],
                    "account_sid": os.getenv("TWILIO_ACCOUNT_SID", ""),
                }
            }

            logger.info(f"👤 Starting bot with meta: {meta}")
            
            # Run the bot - this blocks until the call ends
            try:
                await run_bot(transport, runner_args, meta)
                logger.info("✅ Bot completed successfully")
            except Exception as bot_error:
                logger.error(f"❌ Bot error: {bot_error}", exc_info=True)
                raise
            
            return

    except Exception as e:
        logger.error(f"❌ Transport detection/setup failed: {e}", exc_info=True)
        try:
            await runner_args.websocket.close()
        except:
            pass
        raise

async def bot2(runner_args: RunnerArguments):
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

    # ─────────────────────────────
    # Try Twilio detection first
    # ─────────────────────────────
    try:
        transport_type, call_data = await parse_telephony_websocket(runner_args.websocket)
        logger.info(f"📞 Detected transport type: {transport_type}")
        print(">>>>>>>>>  x1")
        if transport_type == "twilio":
            print(">>>>>>>>>  x2")
            caller_number = call_data.get("body", {}).get("from", "")
            to_number = call_data.get("body", {}).get("to", "")
            logger.info(f"📱 Twilio caller number: {caller_number} → {to_number}")
            
            print(">>>>>>>>>  x3")
            serializer = TwilioFrameSerializer(
                stream_sid=call_data["stream_id"],
                call_sid=call_data["call_id"],
                account_sid=os.getenv("TWILIO_ACCOUNT_SID", ""),
                auth_token=os.getenv("TWILIO_AUTH_TOKEN", ""),
            )

            print(">>>>>>>>>  x4")

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

            print(">>>>>>>>>  x5")

            meta = {
                "type": "client",
                "channel" : "call",
                "session": "",
                "language": "en",
                "metadata": {
                    "caller": caller_number,
                    "recipient": to_number,
                    "call_sid": call_data["call_id"],
                    "stream_sid": call_data["stream_id"],
                    "account_sid": os.getenv("TWILIO_ACCOUNT_SID", ""),
                }
            }

            print(">>>>>>>>>  x6")

            logger.info(f"👤 Twilio context: {meta}")

            print(">>>>>>>>>  x7")
            await run_bot(transport, runner_args, meta)
            print(">>>>>>>>>  x8")
            return

    except Exception as e:
        logger.info(f"ℹ️ Not a Twilio connection, falling back to WebRTC: {e}")

    # ─────────────────────────────
    # WebRTC fallback
    # ─────────────────────────────
    # try:
    #     logger.info("🌐 Using WebRTC transport")


        

    #     # Manually build transport (since create_transport doesn't accept force_type)
    #     params = TransportParams(
    #         audio_in_enabled=True,
    #         audio_in_filter=krisp_filter,
    #         audio_out_enabled=True,
    #         vad_analyzer=SileroVADAnalyzer(params=VADParams(stop_secs=0.5)),
    #         serializer=ProtobufFrameSerializer(),  # 
    #     )

    #     transport = FastAPIWebsocketTransport(
    #         websocket=runner_args.websocket,
    #         params=FastAPIWebsocketParams(**params.__dict__)
    #     )

    #     meta = {
    #         "branch": "123456",
    #         "type": "business",
    #         "channel": "webrtc",
    #         "language": "en",
    #         "session": "",
    #         "metadata" : {}
    #     }

    #     logger.info(f"👤 WebRTC context: {meta}")
    #     await run_bot(transport, runner_args, meta=meta)

    # except Exception as e:
    #     logger.error(f"❌ Failed to initialize WebRTC transport: {e}", exc_info=True)
    #     await runner_args.websocket.close()

    # finally:
    #     logger.info("🧹 Bot session ended. Connection closed.")

        

# -------------------------------------------------------
# Main Entry (for local or Pipecat Cloud)
# -------------------------------------------------------

if __name__ == "__main__":
    from pipecat.runner.run import main
    main()