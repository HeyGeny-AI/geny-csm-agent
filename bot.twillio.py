#
# Copyright (c) 2024–2025, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

"""Gemini Live + Twilio + NestJS MCP Booking Example (Merged Version)."""

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
from pipecat.runner.utils import parse_telephony_websocket
from pipecat.serializers.twilio import TwilioFrameSerializer
from pipecat.services.google.gemini_live.llm import GeminiLiveLLMService
from pipecat.services.llm_service import FunctionCallParams
from pipecat.transports.websocket.fastapi import FastAPIWebsocketTransport, FastAPIWebsocketParams

load_dotenv(override=True)

NUM_ROUNDS = 4


# -------------------------------------------------------
# NestJS MCP Client
# -------------------------------------------------------

class NestJSMCPClient:
    """HTTP client for NestJS MCP server."""
    
    def __init__(self, base_url: str, api_key: str = ""):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.session: Optional[aiohttp.ClientSession] = None
    
    def _get_headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers
    
    async def _ensure_session(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
    
    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()
    
    async def health_check(self) -> Dict[str, Any]:
        await self._ensure_session()
        url = f"{self.base_url}/mcp/health"
        async with self.session.get(url, headers=self._get_headers()) as resp:
            resp.raise_for_status()
            return await resp.json()
    
    async def list_tools(self) -> Dict[str, Any]:
        await self._ensure_session()
        url = f"{self.base_url}/mcp/tools"
        async with self.session.get(url, headers=self._get_headers()) as resp:
            resp.raise_for_status()
            return await resp.json()
    
    async def call_tool(self, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        await self._ensure_session()
        url = f"{self.base_url}/mcp/call-tool"
        payload = {"name": tool_name, "args": args}
        async with self.session.post(url, json=payload, headers=self._get_headers()) as resp:
            resp.raise_for_status()
            return await resp.json()
    
    async def make_booking(self, name: str, phone: str, service: str, timestamp: int) -> Dict[str, Any]:
        args = {"name": name, "phone": phone, "service": service, "timestamp": timestamp}
        logger.info(f"Making booking: {args}")
        return await self.call_tool("make_booking", args)
    
    async def get_bookings(self, name: str) -> Dict[str, Any]:
        args = {"name": name}
        logger.info(f"Getting bookings for: {name}")
        return await self.call_tool("get_bookings", args)


# -------------------------------------------------------
# Booking Handlers
# -------------------------------------------------------

def booking_handlers_factory(mcp_client: NestJSMCPClient, default_phone: str = ""):
    """
    Creates all booking-related async handler functions with shared context
    (NestJS MCP client + caller phone number).
    """

    logger.info(f"📱 Caller number detected inside booking_handlers_factory: {default_phone}")

    # ---------------------------------------------------
    # 1️⃣  MAKE BOOKING HANDLER
    # ---------------------------------------------------
    async def make_booking_handler(params: FunctionCallParams):
        logger.info(f"📱 Caller number inside make_booking_handler: {default_phone}")
        arguments = params.arguments or {}
        logger.info(f"Received booking request: {arguments}")

        try:
            name = arguments.get("name")
            phone = arguments.get("phone") or default_phone
            service = arguments.get("service")
            date = arguments.get("date")
            time = arguments.get("time")

            # Ask user for phone if missing
            if not phone:
                await params.result_callback({
                    "status": "missing_info",
                    "message": "I don’t have your phone number yet. Could you please provide it so I can complete your booking?"
                })
                return

            # Validate inputs
            if not all([name, phone, service, date, time]):
                raise ValueError("Missing required booking fields")

            # Convert date/time → timestamp
            datetime_str = f"{date} {time}"
            dt = datetime.strptime(datetime_str, "%Y-%m-%d %H:%M")
            lagos_tz = pytz.timezone("Africa/Lagos")
            dt = lagos_tz.localize(dt)
            timestamp = int(dt.timestamp())

            # Call NestJS MCP booking endpoint
            result = await mcp_client.make_booking(name, phone, service, timestamp)
            msg = result.get("content", [{}])[0].get("text", "Booking created successfully.")

            await params.result_callback({
                "status": "success",
                "message": msg,
                "confirmation": result
            })

        except Exception as e:
            logger.error(f"Booking failed: {e}")
            await params.result_callback({
                "status": "error",
                "message": str(e)
            })

    # ---------------------------------------------------
    # 2️⃣  GET BOOKINGS HANDLER
    # ---------------------------------------------------
    async def get_bookings_handler(params: FunctionCallParams):
        arguments = params.arguments or {}
        name = arguments.get("name", "")
        if not name:
            await params.result_callback({
                "status": "error",
                "message": "Customer name is required"
            })
            return

        try:
            result = await mcp_client.get_bookings(name)
            msg = result.get("content", [{}])[0].get("text", "No bookings found.")

            await params.result_callback({
                "status": "success",
                "bookings": msg
            })

        except Exception as e:
            logger.error(f"Failed to get bookings: {e}")
            await params.result_callback({
                "status": "error",
                "message": str(e)
            })

    # ---------------------------------------------------
    # 3️⃣  (OPTIONAL FUTURE EXTENSIONS)
    # ---------------------------------------------------
    # async def cancel_booking_handler(...)
    # async def get_services_handler(...)

    # Return all handlers together
    return {
        "make_booking": make_booking_handler,
        "get_bookings": get_bookings_handler,
    }



# def booking_handlers_factory(mcp_client: NestJSMCPClient, default_phone: str = ""):
#     logger.info(f"📱 Caller number detected in inside make_booking_handler_factory : {default_phone}")

#     async def make_booking_handler(params: FunctionCallParams):

#         logger.info(f"📱 Caller number detected in inside make_booking_handler function : {default_phone}")
#         arguments = params.arguments or {}
#         logger.info(f"Received booking request: {arguments}")
#         try:
#             name = arguments.get("name")
#             phone = arguments.get("phone") or default_phone
#             service = arguments.get("service")
#             date = arguments.get("date")
#             time = arguments.get("time")

#             # If default phone is missing, ask user for it conversationally
#             if not phone:
#                 await params.result_callback({
#                     "status": "missing_info",
#                     "message": "I don’t have your phone number yet. Could you please provide it so I can complete your booking?"
#                 })
#                 return
            
#             if not all([name, phone, service, date, time]):
#                 raise ValueError("Missing required booking fields")

#             datetime_str = f"{date} {time}"
#             dt = datetime.strptime(datetime_str, "%Y-%m-%d %H:%M")
#             lagos_tz = pytz.timezone("Africa/Lagos")
#             dt = lagos_tz.localize(dt)
#             timestamp = int(dt.timestamp())

#             result = await mcp_client.make_booking(name, phone, service, timestamp)
#             msg = result.get("content", [{}])[0].get("text", "Booking created successfully.")
#             await params.result_callback({"status": "success", "message": msg, "confirmation": result})
#         except Exception as e:
#             logger.error(f"Booking failed: {e}")
#             await params.result_callback({"status": "error", "message": str(e)})
#     return make_booking_handler


# def get_bookings_handler_factory(mcp_client: NestJSMCPClient):
#     async def get_bookings_handler(params: FunctionCallParams):
#         arguments = params.arguments or {}
#         name = arguments.get("name", "")
#         if not name:
#             await params.result_callback({"status": "error", "message": "Customer name is required"})
#             return
#         try:
#             result = await mcp_client.get_bookings(name)
#             msg = result.get("content", [{}])[0].get("text", "No bookings found.")
#             await params.result_callback({"status": "success", "bookings": msg})
#         except Exception as e:
#             logger.error(f"Failed to get bookings: {e}")
#             await params.result_callback({"status": "error", "message": str(e)})
#     return get_bookings_handler


# -------------------------------------------------------
# Gemini + Twilio Bot
# -------------------------------------------------------

async def run_bot(transport: FastAPIWebsocketTransport, runner_args: RunnerArguments, caller_number: str = ""):
    logger.info("🚀 Starting Gemini + Twilio booking bot")


    logger.info(f"📱 Caller number detected in inside run_bot : {caller_number}")

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

    # Define Gemini functions
    make_booking_function = FunctionSchema(
        name="make_booking",
        description="Create a new booking appointment.",
        properties={
            "name": {"type": "string"},
            "phone": {"type": "string"},
            "service": {"type": "string"},
            "date": {"type": "string"},
            "time": {"type": "string"},
        },
        required=["name", "service", "date", "time"],
    )

    get_bookings_function = FunctionSchema(
        name="get_bookings",
        description="Retrieve bookings by customer name.",
        properties={"name": {"type": "string"}},
        required=["name"],
    )

    cancel_booking_function = FunctionSchema(
        name="cancel_booking",
        description="cancel bookings by customer name.",
        properties={"name": {"type": "string"}},
        required=["name"],
    )


    get_services_function = FunctionSchema(
        name="get_services",
        description="get branch services and prices.",
        properties={"name": {"type": "string"}},
        required=["name"],
    )

    tools = ToolsSchema(standard_tools=[make_booking_function, get_bookings_function, cancel_bookings_function, get_services_function])

    # System instructions for Gemini
    instructions = """
You are Geny, a friendly voice assistant who helps users book appointments or check their bookings.
Always confirm details before making a booking.
Use date format YYYY-MM-DD and time in 24-hour HH:MM.
Be concise, polite, and natural in your voice responses.
"""

    # Gemini LLM service (keeps your original Gemini config)
    llm = GeminiLiveLLMService(
        api_key=os.getenv("GOOGLE_API_KEY"),
        model="models/gemini-2.5-flash-native-audio-preview-09-2025",
        voice_id="Charon",
        system_instruction=instructions,
        tools=tools,
    )

    handlers = booking_handlers_factory(mcp_client, default_phone=caller_number)
    # Register handlers
    llm.register_function("make_booking", handlers["make_booking"])
    llm.register_function("get_bookings", handlers["get_bookings"])
    llm.register_function("cancel_bookings", handlers["cancel_bookings"])
    llm.register_function("get_services", handlers["get_services"])
    

    # Conversation context
    messages = [{"role": "user", "content": "Hi Geny, can you help me book a service?"}]
   
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
        logger.info("📞 Client connected via Twilio")
        await task.queue_frames([LLMRunFrame()])

    @transport.event_handler("on_client_disconnected")
    async def on_disconnect(transport, client):
        logger.info("👋 Client disconnected")
        await task.cancel()
        await mcp_client.close()

    @transcript.event_handler("on_transcript_update")
    async def on_transcript(processor, frame):
        for msg in frame.messages:
            if isinstance(msg, TranscriptionMessage):
                logger.info(f"{msg.role}: {msg.content}")

    runner = PipelineRunner(handle_sigint=runner_args.handle_sigint)
    try:
        await runner.run(task)
    finally:
        await mcp_client.close()


# -------------------------------------------------------
# Twilio Transport Entry Point
# -------------------------------------------------------

async def bot(runner_args: RunnerArguments):

    print("🚀 Starting Gemini + Twilio booking bot")

    """Main bot entry point for Twilio audio calls (Gemini-powered)."""
    transport_type, call_data = await parse_telephony_websocket(runner_args.websocket)
    logger.info(f"📞 Detected Twilio transport: {transport_type}")

    serializer = TwilioFrameSerializer(
        stream_sid=call_data["stream_id"],
        call_sid=call_data["call_id"],
        account_sid=os.getenv("TWILIO_ACCOUNT_SID", ""),
        auth_token=os.getenv("TWILIO_AUTH_TOKEN", ""),
    )

    # Optional noise filter
    if os.environ.get("ENV") != "local":
        from pipecat.audio.filters.krisp_filter import KrispFilter
        krisp_filter = KrispFilter()
    else:
        krisp_filter = None

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

  
    caller_number = call_data.get("body", {}).get("from", "")

    logger.info(f"📱 Caller number detected in bot.py: {caller_number}")

    await run_bot(transport, runner_args, caller_number)


# -------------------------------------------------------
# Main Entry (for local or Pipecat Cloud)
# -------------------------------------------------------

if __name__ == "__main__":
    from pipecat.runner.run import main
    main()
