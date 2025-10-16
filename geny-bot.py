#
# Copyright (c) 2024–2025, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

"""Gemini Live + Twilio + NestJS MCP Booking Example."""

import asyncio
import os
from dotenv import load_dotenv
from loguru import logger

from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import EndTaskFrame, LLMRunFrame, TranscriptionMessage
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContext
from pipecat.processors.frame_processor import FrameDirection
from pipecat.processors.frameworks.rtvi import RTVIConfig, RTVIObserver, RTVIProcessor
from pipecat.processors.transcript_processor import TranscriptProcessor
from pipecat.runner.types import RunnerArguments
from pipecat.runner.utils import create_transport
from pipecat.services.google.gemini_live.llm import GeminiLiveLLMService
from pipecat.services.llm_service import FunctionCallParams
from pipecat.transports.base_transport import BaseTransport, TransportParams
from pipecat.transports.websocket.fastapi import FastAPIWebsocketParams
from datetime import datetime
import pytz


# from game_content import GameContent
# from botclient import NestJSMCPClient  # Import the new client

load_dotenv(override=True)

NUM_ROUNDS = 4


"""
HTTP client for NestJS MCP server.
Communicates with booking MCP tools via REST API.
"""

import aiohttp
from loguru import logger
from typing import Optional, Dict, Any


class NestJSMCPClient:
    """HTTP client for NestJS MCP server."""
    
    def __init__(self, base_url: str, api_key: str = ""):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.session: Optional[aiohttp.ClientSession] = None
    
    def _get_headers(self) -> Dict[str, str]:
        """Get headers for HTTP requests."""
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers
    
    async def _ensure_session(self):
        """Ensure aiohttp session exists."""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
    
    async def close(self):
        """Close the HTTP session."""
        if self.session and not self.session.closed:
            await self.session.close()
    
    async def health_check(self) -> Dict[str, Any]:
        """Check MCP server health."""
        await self._ensure_session()
        url = f"{self.base_url}/mcp/health"
        
        try:
            async with self.session.get(url, headers=self._get_headers()) as resp:
                resp.raise_for_status()
                return await resp.json()
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            raise
    
    async def list_tools(self) -> Dict[str, Any]:
        """List available MCP tools."""
        await self._ensure_session()
        url = f"{self.base_url}/mcp/tools"
        
        try:
            async with self.session.get(url, headers=self._get_headers()) as resp:
                resp.raise_for_status()
                return await resp.json()
        except Exception as e:
            logger.error(f"Failed to list tools: {e}")
            raise
    
    async def call_tool(self, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Call an MCP tool via HTTP.
        
        Args:
            tool_name: Name of the tool to call
            args: Arguments for the tool
            
        Returns:
            Tool execution result
        """
        await self._ensure_session()
        # FIX: Use kebab-case URL to match NestJS @Post('call-tool')
        url = f"{self.base_url}/mcp/call-tool"
        
        payload = {
            "name": tool_name,
            "args": args
        }
        
        try:
            async with self.session.post(
                url, 
                json=payload, 
                headers=self._get_headers()
            ) as resp:
                resp.raise_for_status()
                return await resp.json()
        except aiohttp.ClientResponseError as e:
            logger.error(f"Tool call failed ({e.status}): {e.message}")
            raise
        except Exception as e:
            logger.error(f"Tool call failed: {e}")
            raise
    
    async def make_booking(
        self, 
        name: str, 
        phone: str, 
        service: str, 
        timestamp: int, 
    ) -> Dict[str, Any]:
        """
        Create a new booking.
        
        Args:
            name: Customer name
            phone: Customer phone
            service: Service type
            timestamp: timestamp
            
        Returns:
            Booking confirmation
        """
        args = {
            "name": name,
            "service": service,
            "phone": phone,
            "timestamp": timestamp
        }
        
        logger.info(f"Making booking: {args}")
        return await self.call_tool("make_booking", args)
    
    async def get_bookings(self, name: str) -> Dict[str, Any]:
        """
        Retrieve bookings for a customer.
        
        Args:
            name: Customer name
            
        Returns:
            List of bookings
        """
        args = {"name": name}
        
        logger.info(f"Getting bookings for: {name}")
        return await self.call_tool("get_bookings", args)

# -------------------------------------------------------
# Function handler factory (captures mcp_client)
# -------------------------------------------------------

def make_booking_handler_factory(mcp_client: NestJSMCPClient):
    """Factory to create booking handler with MCP client closure."""
    
    async def make_booking_handler(params: FunctionCallParams):
        """Handle make_booking function call via NestJS MCP server."""
        arguments = params.arguments or {}
        logger.info(f"Received booking request from LLM: {arguments}")

        try:
            # Extract booking details
            name = arguments.get("name")
            phone = arguments.get("phone")
            service = arguments.get("service")
            date = arguments.get("date")
            time = arguments.get("time")

            # Validate required fields
            if not all([name, phone, service, date, time]):
                missing = [k for k in ["name", "phone", "service", "date", "time"] if not arguments.get(k)]
                raise ValueError(f"Missing required fields: {', '.join(missing)}")

            # Convert date and time to timestamp
            try:
                # Combine date and time strings
                datetime_str = f"{date} {time}"
                # Parse the datetime
                dt = datetime.strptime(datetime_str, "%Y-%m-%d %H:%M")
                
                # Set timezone (adjust to your actual timezone)
                # Note: Lagos is 'Africa/Lagos', not 'America/Los_Angeles'
                lagos_tz = pytz.timezone('America/Los_Angeles')
                dt = lagos_tz.localize(dt)
                
                # Convert to Unix timestamp (seconds since epoch)
                timestamp = int(dt.timestamp())
                
                logger.info(f"Converted {datetime_str} to timestamp: {timestamp}")
                
            except ValueError as e:
                logger.error(f"Failed to parse date/time: {e}")
                raise ValueError(f"Invalid date/time format. Expected date: daym month and year, time: hour and minute")

            # Call NestJS MCP server
            result = await mcp_client.make_booking(name, phone, service, timestamp)
            
            # Parse the MCP response
            if result.get("content") and len(result["content"]) > 0:
                content_text = result["content"][0].get("text", "")
                logger.info(f"✅ Booking successful: {content_text}")
                
                await params.result_callback({
                    "status": "success",
                    "message": content_text,
                    "confirmation": result
                })
            else:
                logger.warning(f"Unexpected MCP response format: {result}")
                await params.result_callback({
                    "status": "success",
                    "message": "Booking created successfully",
                    "raw_response": result
                })
                
        except Exception as e:
            logger.error(f"❌ Booking failed: {e}")
            await params.result_callback({
                "status": "error",
                "message": f"Failed to create booking: {str(e)}"
            })

    return make_booking_handler


def get_bookings_handler_factory(mcp_client: NestJSMCPClient):
    """Factory to create get bookings handler with MCP client closure."""
    
    async def get_bookings_handler(params: FunctionCallParams):
        """Handle get_bookings function call via NestJS MCP server."""
        arguments = params.arguments or {}
        logger.info(f"Received get bookings request: {arguments}")

        try:
            name = arguments.get("name", "")
            
            if not name:
                raise ValueError("Customer name is required")

            # Call NestJS MCP server
            result = await mcp_client.get_bookings(name)
            
            # Parse the MCP response
            if result.get("content") and len(result["content"]) > 0:
                content_text = result["content"][0].get("text", "")
                logger.info(f"✅ Retrieved bookings: {content_text}")
                
                await params.result_callback({
                    "status": "success",
                    "bookings": content_text
                })
            else:
                await params.result_callback({
                    "status": "success",
                    "bookings": "No bookings found"
                })
                
        except Exception as e:
            logger.error(f"❌ Failed to retrieve bookings: {e}")
            await params.result_callback({
                "status": "error",
                "message": f"Failed to retrieve bookings: {str(e)}"
            })

    return get_bookings_handler


# -------------------------------------------------------
# Game end handler
# -------------------------------------------------------

async def end_game_handler(params: FunctionCallParams):
    """Handle end_game function call."""
    logger.info("🎮 Game ended - pushing EndTaskFrame")
    await params.result_callback({"status": "game_ended"})
    await asyncio.sleep(3)
    await params.llm.push_frame(EndTaskFrame(), FrameDirection.UPSTREAM)


# -------------------------------------------------------
# Main bot logic
# -------------------------------------------------------

async def run_bot(transport: BaseTransport, runner_args: RunnerArguments):
    logger.info("🚀 Starting bot...")

    # Initialize NestJS MCP client
    mcp_base_url = os.getenv("MCP_SERVER_URL", "http://localhost:3004")
    mcp_api_key = os.getenv("MCP_API_KEY", "")
    
    mcp_client = NestJSMCPClient(base_url=mcp_base_url, api_key=mcp_api_key)
    
    # Test connection to MCP server
    try:
        health = await mcp_client.health_check()
        logger.info(f"✅ MCP server health: {health}")
        
        # Optional: List available tools
        tools_list = await mcp_client.list_tools()
        logger.info(f"📋 Available MCP tools: {tools_list}")
    except Exception as e:
        logger.warning(f"⚠️ Could not connect to MCP server: {e}")
        logger.warning("Bot will continue, but booking features may not work")

    # Prepare game content
    # game = GameContent(num_rounds=NUM_ROUNDS)
    # all_rounds = game.get_formatted_rounds()

    # Define callable functions for Gemini
    # end_game_function = FunctionSchema(
    #     name="end_game",
    #     description=f"Call this after completing all {NUM_ROUNDS} rounds to end the game and say goodbye.",
    #     properties={},
    #     required=[],
    # )


    make_booking_function = FunctionSchema(
        name="make_booking",
        description="Create a new booking. Collects customer name, phone, service, date, and time.",
        properties={
            "name": {"type": "string", "description": "Customer's full name"},
            "phone": {"type": "string", "description": "Customer's phone number"},
            "service": {"type": "string", "description": "Service to book (e.g., Haircut, Massage, Nails, Braids, Dreadlocks, etc.)"},
            "date": {"type": "string", "description": "Appointment date in YYYY-MM-DD format"},
            "time": {"type": "string", "description": "Appointment time in HH:MM format (24-hour)"},
        },
        required=["name", "phone", "service", "date", "time"],
    )

    get_bookings_function = FunctionSchema(
        name="get_bookings",
        description="Retrieve existing bookings for a customer by name.",
        properties={
            "name": {"type": "string", "description": "Customer name to search for"},
        },
        required=["name"],
    )

    tools = ToolsSchema(
        standard_tools=[make_booking_function, get_bookings_function]
    )

    # Fix 3: Update the system instructions to match
    instructions = f"""
Your name is Geny, you are a friendly voice assistant with these abilities:
1. Help users make booking appointments
2. Look up existing bookings

BOOKING MODE:
- To create a booking: ask for name, phone, service, date (date, month and year), and time (hour and minute in 24-hour format)
- Use the date and time formats exactly as specified
- Confirm all details with the user before creating the booking

Be concise, friendly, and helpful. Keep responses short and conversational.
"""

    llm = GeminiLiveLLMService(
        api_key=os.getenv("GOOGLE_API_KEY"),
        model="models/gemini-2.5-flash-native-audio-preview-09-2025",
        voice_id="Charon",
        system_instruction=instructions,
        tools=tools,
    )

    # Register functions with closures to access mcp_client
    # llm.register_function("end_game", end_game_handler)
    llm.register_function("make_booking", make_booking_handler_factory(mcp_client))
    llm.register_function("get_bookings", get_bookings_handler_factory(mcp_client))

    # Initial user prompt
    messages = [
        {
            "role": "user",
            "content": (
                "Hi! Your name is Geny, You can help me book for services, look up my bookings, "
                "and ask what I'd like to do."
            ),
        },
    ]

    context = OpenAILLMContext(messages)
    context_aggregator = llm.create_context_aggregator(context)
    transcript = TranscriptProcessor()
    rtvi = RTVIProcessor(config=RTVIConfig(config=[]))

    pipeline = Pipeline(
        [
            transport.input(),
            rtvi,
            context_aggregator.user(),
            transcript.user(),
            llm,
            transport.output(),
            transcript.assistant(),
            context_aggregator.assistant(),
        ]
    )

    task = PipelineTask(
        pipeline,
        params=PipelineParams(enable_metrics=True, enable_usage_metrics=True),
        idle_timeout_secs=runner_args.pipeline_idle_timeout_secs,
        observers=[RTVIObserver(rtvi)],
    )

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        logger.info("👤 Client connected")
        await task.queue_frames([LLMRunFrame()])

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        logger.info("👋 Client disconnected")
        await task.cancel()
        # Close MCP client session
        try:
            await mcp_client.close()
        except Exception as e:
            logger.warning(f"Error closing MCP client: {e}")

    @transcript.event_handler("on_transcript_update")
    async def on_transcript_update(processor, frame):
        for msg in frame.messages:
            if isinstance(msg, TranscriptionMessage):
                timestamp = f"[{msg.timestamp}] " if msg.timestamp else ""
                logger.info(f"{timestamp}{msg.role}: {msg.content}")

    runner = PipelineRunner(handle_sigint=runner_args.handle_sigint)

    # Ensure session is closed on exit
    try:
        await runner.run(task)
    finally:
        try:
            await mcp_client.close()
        except Exception:
            pass


# -------------------------------------------------------
# Entry point
# -------------------------------------------------------

async def bot(runner_args: RunnerArguments):
    """Main bot entry point compatible with Pipecat Cloud."""
    if os.environ.get("ENV") != "local":
        from pipecat.audio.filters.krisp_filter import KrispFilter
        krisp_filter = KrispFilter()
    else:
        krisp_filter = None

    transport_params = {
        "twilio": lambda: FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_in_filter=krisp_filter,
            audio_out_enabled=True,
            vad_analyzer=SileroVADAnalyzer(params=VADParams(stop_secs=0.5)),
        ),
        "webrtc": lambda: TransportParams(
            audio_in_enabled=True,
            audio_in_filter=krisp_filter,
            audio_out_enabled=True,
            vad_analyzer=SileroVADAnalyzer(params=VADParams(stop_secs=0.5)),
        ),
    }

    transport = await create_transport(runner_args, transport_params)
    await run_bot(transport, runner_args)


if __name__ == "__main__":
    from pipecat.runner.run import main
    main()