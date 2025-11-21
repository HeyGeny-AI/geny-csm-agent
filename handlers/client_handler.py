
# booking_handlers.py

from datetime import datetime
import pytz
from loguru import logger
from typing import Dict, Any
from pipecat.services.llm_service import FunctionCallParams
from mcp_client import NestJSMCPClient   # Make sure path is correct
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.adapters.schemas.function_schema import FunctionSchema


class ClientHandlers:
    """Grouped booking handlers for Gemini function-calling."""


    def __init__(self, mcp_client: NestJSMCPClient, default_phone: str = ""):
        self.mcp_client = mcp_client
        self.default_phone = default_phone

    def get_instructions(self):
        # System instructions for Gemini (context-aware of phone number)
        phone_context = f"The caller's phone number is {self.default_phone}." if self.default_phone else "Ask for the caller's phone number if needed for booking."
                
        instructions = f"""
            You are Geny, a friendly voice assistant who helps users book appointments or check their bookings.
            Always confirm details before making a booking.
            Use date format YYYY-MM-DD and time in 24-hour HH:MM.
            Be concise, polite, and natural in your voice responses.

            IMPORTANT RULES ABOUT CUSTOMER NAME:
            - Never assume the caller’s name.
            - Never use a placeholder like “User”, “Guest”, or any inferred name.
            - If the name is not explicitly provided by the caller, ALWAYS ask: 
            “May I have your name, please?”
            - Do not proceed with a booking or lookup until the caller provides their name.
            {phone_context}
            """
        
        return instructions

    # Define Gemini functions
    make_booking_function = FunctionSchema(
        name="make_booking",
        description="Create a new booking appointment.",
        properties={
            "name": {"type": "string", "description": "Customer name"},
            "phone": {"type": "string", "description": "Customer phone number"},
            "service": {"type": "string", "description": "Service type"},
            "date": {"type": "string", "description": "Date in YYYY-MM-DD format"},
            "time": {"type": "string", "description": "Time in HH:MM 24-hour format"},
        },
        required=["name", "service", "date", "time"],
    )

    get_bookings_function = FunctionSchema(
        name="get_bookings",
        description="Retrieve bookings by customer name.",
        properties={"name": {"type": "string", "description": "Customer name"}},
        required=["name"],
    )

    cancel_bookings_function = FunctionSchema(
        name="cancel_bookings",
        description="Cancel bookings by customer name.",
        properties={"name": {"type": "string", "description": "Customer name"}},
        required=["name"],
    )

    get_services_function = FunctionSchema(
        name="get_services",
        description="Get available branch services and prices.",
        properties={"name": {"type": "string", "description": "Branch or service category"}},
        required=[],
    )

    tools = ToolsSchema(standard_tools=[
        make_booking_function, 
        get_bookings_function, 
        cancel_bookings_function, 
        get_services_function
    ])

    # ---------------------------------------------------------
    # MAKE BOOKING
    # ---------------------------------------------------------
    async def make_booking(self, params: FunctionCallParams):
        arguments = params.arguments or {}
        logger.info(f"Received booking request: {arguments}")

        try:
            name = arguments.get("name")
            phone = arguments.get("phone") or self.default_phone
            service = arguments.get("service")
            date = arguments.get("date")
            time = arguments.get("time")

            if not name or name.lower() == "user":
                await params.result_callback({
                    "status": "missing_info",
                    "message": "I don't have your name yet. What name should I use for the booking?"
                })
                return

            if not phone:
                await params.result_callback({
                    "status": "missing_info",
                    "message": "I don't have your phone number yet. Could you please provide it?"
                })
                return

            if not all([name, phone, service, date, time]):
                raise ValueError("Missing required booking fields")

            dt = datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M")
            lagos = pytz.timezone("Africa/Lagos")
            timestamp = int(lagos.localize(dt).timestamp())

            result = await self.mcp_client.make_booking(name, phone, service, timestamp)
            msg = result.get("content", [{}])[0].get("text", "Booking created successfully.")

            await params.result_callback({
                "status": "success",
                "message": msg,
                "confirmation": result
            })

        except Exception as e:
            logger.error(f"Booking failed: {e}")
            await params.result_callback({"status": "error", "message": str(e)})

    # ---------------------------------------------------------
    # GET BOOKINGS
    # ---------------------------------------------------------
    async def get_bookings(self, params: FunctionCallParams):
        arguments = params.arguments or {}
        name = arguments.get("name", "")

        if not name:
            await params.result_callback({"status": "error", "message": "Customer name is required"})
            return

        try:
            result = await self.mcp_client.get_bookings(name)
            msg = result.get("content", [{}])[0].get("text", "No bookings found.")

            await params.result_callback({"status": "success", "bookings": msg})

        except Exception as e:
            logger.error(f"Failed to get bookings: {e}")
            await params.result_callback({"status": "error", "message": str(e)})

    # ---------------------------------------------------------
    # CANCEL BOOKINGS
    # ---------------------------------------------------------
    async def cancel_bookings(self, params: FunctionCallParams):
        arguments = params.arguments or {}
        name = arguments.get("name", "")

        if not name:
            await params.result_callback({"status": "error", "message": "Customer name is required"})
            return

        try:
            result = await self.mcp_client.call_tool("cancel_bookings", {"name": name})
            msg = result.get("content", [{}])[0].get("text", "Booking cancelled successfully.")

            await params.result_callback({"status": "success", "message": msg})

        except Exception as e:
            logger.error(f"Failed to cancel booking: {e}")
            await params.result_callback({"status": "error", "message": str(e)})

    # ---------------------------------------------------------
    # GET SERVICES
    # ---------------------------------------------------------
    async def get_services(self, params: FunctionCallParams):
        arguments = params.arguments or {}
        name = arguments.get("name", "")

        try:
            result = await self.mcp_client.call_tool("get_services", {"name": name})
            msg = result.get("content", [{}])[0].get("text", "No services found.")

            await params.result_callback({"status": "success", "services": msg})

        except Exception as e:
            logger.error(f"Failed to get services: {e}")
            await params.result_callback({"status": "error", "message": str(e)})



# -------------------------------------------------------
# Booking Handlers
# -------------------------------------------------------

def booking_client_handlers_factory(mcp_client: NestJSMCPClient, default_phone: str = ""):
    """
    Creates all booking-related async handler functions with shared context
    (NestJS MCP client + caller phone number).
    """

    logger.info(f"📱 Caller number in booking_handlers_factory: {default_phone}")

    # ---------------------------------------------------
    # 1️⃣  MAKE BOOKING HANDLER
    # ---------------------------------------------------
    async def make_booking_handler(params: FunctionCallParams):
        arguments = params.arguments or {}
        logger.info(f"Received booking request: {arguments}")

        try:
            name = arguments.get("name")
            phone = arguments.get("phone") or default_phone
            service = arguments.get("service")
            date = arguments.get("date")
            time = arguments.get("time")

            # Require a real name — do NOT allow defaults like "User"
            if not name or name.lower() == "user":
                await params.result_callback({
                    "status": "missing_info",
                    "message": "I don't have your name yet. What name should I use for the booking?"
                })
                return

            # Ask user for phone if missing
            if not phone:
                await params.result_callback({
                    "status": "missing_info",
                    "message": "I don't have your phone number yet. Could you please provide it so I can complete your booking?"
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
    # 3️⃣  CANCEL BOOKINGS HANDLER
    # ---------------------------------------------------
    async def cancel_bookings_handler(params: FunctionCallParams):
        arguments = params.arguments or {}
        name = arguments.get("name", "")
        if not name:
            await params.result_callback({
                "status": "error",
                "message": "Customer name is required"
            })
            return

        try:
            result = await mcp_client.call_tool("cancel_bookings", {"name": name})
            msg = result.get("content", [{}])[0].get("text", "Booking cancelled successfully.")

            await params.result_callback({
                "status": "success",
                "message": msg
            })

        except Exception as e:
            logger.error(f"Failed to cancel booking: {e}")
            await params.result_callback({
                "status": "error",
                "message": str(e)
            })

    # ---------------------------------------------------
    # 4️⃣  GET SERVICES HANDLER
    # ---------------------------------------------------
    async def get_services_handler(params: FunctionCallParams):
        arguments = params.arguments or {}
        name = arguments.get("name", "")

        try:
            result = await mcp_client.call_tool("get_services", {"name": name})
            msg = result.get("content", [{}])[0].get("text", "No services found.")

            await params.result_callback({
                "status": "success",
                "services": msg
            })

        except Exception as e:
            logger.error(f"Failed to get services: {e}")
            await params.result_callback({
                "status": "error",
                "message": str(e)
            })

    # Return all handlers together
    return {
        "make_booking": make_booking_handler,
        "get_bookings": get_bookings_handler,
        "cancel_bookings": cancel_bookings_handler,
        "get_services": get_services_handler,
    }

