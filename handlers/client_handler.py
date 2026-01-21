
# booking_handlers.py

from collections import defaultdict
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


    def __init__(self, mcp_client: NestJSMCPClient, meta: Dict):
        self.mcp_client = mcp_client
        self.meta = meta


    def get_client_greeting(self) -> str:
        """
        Returns a greeting for the caller:
        - If registered: includes first & last name
        - If not registered: generic greeting
        """
        client = self.meta.get("client")
        is_registered = self.meta.get("is_client_registered", False)

        if is_registered and client:
            first_name = client.get("firstName", "").strip()
            last_name = client.get("lastName", "").strip()
            if first_name or last_name:
                return f"Hi {first_name} {last_name}! You have reached {self.meta.get('branch_name', '')}."
        
        # Fallback for unregistered or missing names
        return f"Hi! You have reached {self.meta.get('branch_name', 'our business')}."


    def get_client_instructions(self):
        """
        System instructions for Gemini LLM.
        Guarantees:
        - Registered clients bypass name verification entirely.
        - Only missing booking details (service, date, time) are requested.
        - Uses stored client information safely.
        """

        phone_number = self.meta['metadata']['caller']
        is_registered = self.meta.get("is_client_registered", False)
        client = self.meta.get("client", {})

        instructions = f"""
        You are Geny, a friendly AI voice assistant who helps callers book services and manage bookings.

        ===============================
        📌 CALLER PHONE NUMBER
        ===============================
        The caller's phone number is: {phone_number}

        ===============================
        📌 CLIENT INFORMATION HANDLING
        ===============================
        The backend has already checked whether the caller is registered.
        
        • If `is_client_registered` is True:
            - Use the stored client profile for bookings.
            - NEVER ask for the client's first or last name.
            - NEVER invent names or use placeholders like "User" or "Guest".
            - All booking operations should use the stored profile (name, phone, client ID).

        • If `is_client_registered` is False:
            - Prompt for first name and last name for registration.
            - After registration, continue with booking normally.

        ===============================
        📌 BOOKING RULES
        ===============================
        Before calling make_client_booking:
        - Ensure client is registered.
        - Collect only missing information: service, date (YYYY-MM-DD), and time (HH:MM 24-hour).
        - Branch reference is already provided; never ask for it.
        - Combine first & last name from client profile for the "name" field.
        - Phone is taken from the stored client profile or caller metadata.

        ===============================
        📌 SERVICE LIST RULES
        ===============================
        If the caller asks about services or prices, ALWAYS call get_services.
        Do not guess or invent service items or pricing.

        ===============================
        📌 GENERAL BEHAVIOR
        ===============================
        Be warm, natural, and conversational.
        Always confirm before finalizing a booking.
        Only ask for information that is missing (service, date, time).
        Never ask for names for registered clients.
        """

        return instructions
    
    def get_business_instructions2(self):
        """
        System instructions for Gemini LLM.
        Guarantees:
        - Registered clients bypass name verification entirely.
        - Only missing booking details (service, date, time) are requested.
        - Uses stored client information safely.
        - Can view, create, reschedule, and cancel bookings.
        """

        branch_reference = self.meta['metadata']['branch']
        is_branch_valid = self.meta.get("is_branch_valid", False)
        client = self.meta.get("client", {})

        
        instructions = f"""
        You are Geny, a friendly AI voice assistant who helps business manage bookings and assist walk-in clients.

        ===============================
        📌 BRANCH REFERENCE
        ===============================
        The branch reference is: {branch_reference}

        ===============================
        📌 BRANCH INFORMATION HANDLING
        ===============================
        The backend has already verified whether the branch is valid.

        • If `is_branch_valid` is True:
            - Ask for the client's first and last name only if not registered.
            - NEVER invent names or use placeholders like "User" or "Guest".
            - All booking operations should use the stored profile (name, phone).

        ===============================
        📌 BOOKING RULES
        ===============================
        Before performing any booking operation:
        - Ensure branch is valid.
        - Collect only missing information: service, date.
        - Branch reference is already provided; never ask for it.
        - Combine first & last name from client profile for the "name" field.
        - Request phone number, including country code.
        
        Booking operations you can perform:
        1. **View all bookings** – list all bookings for the branch or a specific client.
        2. **Create a booking** – for walk-in clients or registered clients.
        3. **update a booking** – request only booking code, new date, new time and the service, confirm changes before finalizing.
        4. **Cancel a booking** – confirm before cancellation, never assume.
        5. **check availability** – check the timeslot for when there is an open slot to book.

        ===============================
        📌 GENERAL BEHAVIOR
        ===============================
        Be warm, natural, and conversational.
        Always confirm actions before finalizing (booking, rescheduling, cancellation).
        Only ask for information that is missing.
        Never ask for names for registered clients.
        Ensure privacy and proper handling of all client data.
        DO not switch accent, use one accent for the whole conversation
        """

        return instructions
    
    def get_business_instructions(self):
        """
        System instructions for Gemini LLM with explicit function calling guidance.
        """
        branch_reference = self.meta.get('metadata', {}).get('branch', '')
        is_branch_valid = self.meta.get("is_branch_valid", False)
        business_name = self.meta.get("business", {}).get("name", "our business")
        branch_id = self.meta.get("branch", {}).get("id", "")
        
        instructions = f"""
        You are Geny, a friendly AI voice assistant who helps businesses manage bookings and assist walk-in clients.

        ===============================
        📌 CRITICAL: FUNCTION CALLING
        ===============================
        You MUST use the provided functions to perform operations. NEVER pretend to complete an action without calling the actual function.

        **When to call functions:**
        - When user wants to CREATE a booking → MUST call `make_branch_booking`
        - When user wants to VIEW bookings → MUST call `get_branch_bookings`
        - When user wants to UPDATE a booking → MUST call `update_booking`
        - When user wants to CANCEL a booking → MUST call `cancel_booking`
        - When user wants to CHECK availability → MUST call `get_availability_branch`

        **DO NOT:**
        - Say "let me check" without actually calling the function
        - Say "that time is available" without calling `get_availability_branch`
        - Say "your appointment is booked" without calling `make_branch_booking`
        - Pretend to have information you don't have

        **ALWAYS:**
        - Call the function immediately when you have all required information
        - Wait for the function result before responding
        - Use the actual function response in your reply

        ===============================
        📌 GREETING
        ===============================
        When a business user first connects, greet them warmly:
        - "Hi! You're connected to {business_name}. How can I help you today?"
        
        Keep it natural, friendly, and conversational.

        ===============================
        📌 BRANCH CONTEXT
        ===============================
        - Branch Reference: {branch_reference}
        - Branch ID: {branch_id}
        - Branch Valid: {is_branch_valid}
        - Business Name: {business_name}

        ===============================
        📌 BOOKING WORKFLOW
        ===============================
        For creating a booking, you need:
        1. Customer's first and last name (ask if not provided)
        2. Customer's phone number with country code (ask if not provided)
        3. Service type (ask if not provided)
        4. Date in YYYY-MM-DD format (convert from natural language)
        5. Time in HH:MM 24-hour format (convert from natural language like "5 PM" → "17:00")

        **Example Flow:**
        User: "Book an appointment for my customer"
        You: "I can help with that. What's your customer's name and phone number?"
        User: "John Doe, +1234567890"
        You: "Great! What service does John need?"
        User: "Dreadlocks"
        You: "Perfect. What date and time works best?"
        User: "January 23rd at 5 PM"
        You: [CALL make_branch_booking with: name="John Doe", phone="+1234567890", service="Dreadlocks", date="2026-01-23", time="17:00"]
        [WAIT FOR RESPONSE]
        You: "All set! John's appointment for dreadlocks on January 23rd at 5 PM has been confirmed. The booking code is [CODE FROM RESPONSE]."

        ===============================
        📌 AVAILABILITY CHECKING
        ===============================
        If user asks "is this time available?" or you need to check availability:
        - MUST call `get_availability_branch` with the date
        - Wait for the actual response
        - Use the response to tell the user which times are available

        **Example:**
        User: "Is 5 PM available on January 23rd?"
        You: [CALL get_availability_branch with date="2026-01-23"]
        [WAIT FOR RESPONSE]
        You: "Yes, 5 PM is available on January 23rd" OR "Sorry, 5 PM is booked. Available times are: [LIST FROM RESPONSE]"

        ===============================
        📌 GENERAL BEHAVIOR
        ===============================
        - Be warm, natural, and conversational
        - Always confirm actions before finalizing
        - Only ask for information that is missing
        - Use consistent accent throughout the conversation
        - Ensure privacy and proper handling of client data
        - NEVER invent booking codes or confirmations
        - ALWAYS use function results to provide accurate information
        """
        
        return instructions


    # Define Gemini functions
    make_client_booking_function = FunctionSchema(
        name="make_client_booking",
        description="Create a new booking appointment.",
        properties={
            "name": {"type": "string", "description": "Customer name"},
            "phone": {"type": "string", "description": "Customer phone number"},
            "service": {"type": "string", "description": "Service type"},
            "date": {"type": "string", "description": "Date in YYYY-MM-DD format"},
            "time": {"type": "string", "description": "Time in HH:MM 24-hour format"},
            "branch_reference": {
                "type": "string",
                "description": "Branch reference ID"
            },
        },
        required=["name", "service", "date", "time", "branch_reference"],
    )

    make_branch_booking_function = FunctionSchema(
        name="make_branch_booking",
        description="Create a new booking appointment on behalf of a walk-in customer.",
        properties={
            "name": {"type": "string", "description": "Walk-in Customer name"},
            "phone": {"type": "string", "description": "Walk-in Customer phone number"},
            "service": {"type": "string", "description": "Service type"},
            "date": {"type": "string", "description": "Date in YYYY-MM-DD format"},
            "time": {"type": "string", "description": "Time in HH:MM 24-hour format"},
        },
        required=["name", "phone", "service", "date", "time"],
    )

    get_client_bookings_function = FunctionSchema(
        name="get_client_bookings",
        description="Retrieve bookings by",
        properties={},
        required=[],
    )

    # get_client_availabilty_function = FunctionSchema(
    #     name="update_booking",
    #     description="Update an existing booking from both client and business.",
    #     properties={
    #         "service": {"type": "string", "description": "the service you wanna update to"},
    #         "date": {"type": "string", "description": "new date Date"},
    #         "time": {"type": "string", "description": "new Time"},
    #     },
    #     required=["code", "service", "date", "time"],
    # )


    get_branch_bookings_function = FunctionSchema(
        name="get_branch_bookings",
        description="Retrieve bookings by",
        properties={},
        required=[],
    )

    get_availability_branch_function = FunctionSchema(
        name="get_availability_branch",
        description="get branch availability",
        properties={
            "date": {"type": "string", "description": "date"}, 
        },
        required=["date"],
    )


    cancel_booking_function = FunctionSchema(
        name="cancel_booking",
        description="Cancel bookings by customer name.",
        properties={
            "code": {"type": "string", "description": "Booking code"}, 
            "reason": {"type": "string", "description": "reason for the cancellation"}
        },
        required=["code"],
    )

    get_services_function = FunctionSchema(
        name="get_services",
        description="Get available services and prices.",
        properties={"name": {"type": "string", "description": "Branch or service category"}},
        required=[],
    )


    register_client_function = FunctionSchema(
        name="register_client",
        description="Register a new client.",
        properties={
            "firstName": {"type": "string"},
            "lastName": {"type": "string"},
        },
        required=["firstName", "lastName"],
    )

    update_booking_function = FunctionSchema(
        name="update_booking",
        description="Update an existing booking from both client and business.",
        properties={
            "code": {"type": "string", "description": "the original booking code for the booking"},
            "service": {"type": "string", "description": "the service you wanna update to"},
            "date": {"type": "string", "description": "new date Date"},
            "time": {"type": "string", "description": "new Time"},
        },
        required=["code", "service", "date", "time"],
    )


    client_tools = ToolsSchema(standard_tools=[
        make_client_booking_function, 
        get_client_bookings_function, 
        cancel_booking_function, 
        get_services_function,
        register_client_function,
        update_booking_function,
        get_availability_branch_function
    ])

    business_tools = ToolsSchema(standard_tools=[
        make_branch_booking_function, 
        get_branch_bookings_function,
        cancel_booking_function, 
        update_booking_function,
        get_availability_branch_function
    ])

    # ---------------------------------------------------------
    # MAKE CLIENT BOOKING
    # ---------------------------------------------------------
    async def make_client_booking(self, params: FunctionCallParams):
        arguments = params.arguments or {}
        logger.info(f"Received booking request: {arguments}")

        # Always ensure client is registered
        client = await self.ensure_registered(params)
        if not client:
            return  # unregistered client → registration handled separately

        # Use stored client info for name/phone
        first_name = client.get("firstName", "").strip()
        last_name = client.get("lastName", "").strip()
        name = f"{first_name} {last_name}"
        phone = client.get("phone") or self.meta['metadata']['caller']
        clientId = client.get("id")
        branch_reference = self.meta.get("branch_reference")

        print('*****************************************')
        print(client)
        print(clientId)

        # Only missing booking info triggers a prompt
        service = arguments.get("service")
        date = arguments.get("date")
        time = arguments.get("time")

        missing_fields = [
            field for field, value in {
                "service": service,
                "date": date,
                "time": time
            }.items() if not value
        ]

        if missing_fields:
            await params.result_callback({
                "status": "missing_info",
                "message": f"Please provide the following information: {', '.join(missing_fields)}"
            })
            return

        try:
            # Convert date/time to timestamp
            dt = datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M")
            lagos = pytz.timezone("Africa/Lagos")
            timestamp = int(lagos.localize(dt).timestamp())

            # Make booking via MCP
            result = await self.mcp_client.make_client_booking(
                name=name,
                phone=phone,
                service=service,
                timestamp=timestamp,
                branch_reference=branch_reference,
                clientId=clientId
            )

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



    # ---------------------------------------------------------
    # MAKE BRANCH BOOKING
    # ---------------------------------------------------------
    async def make_branch_booking(self, params: FunctionCallParams):
        arguments = params.arguments or {}
        logger.info(f"Received booking request: {arguments}")

        # Always ensure client is registered
        # client = await self.ensure_registered(params)
        # if not client:
        #     return  # unregistered client → registration handled separately

        # Use stored client info for name/phone
        name = arguments.get("name").strip()
        # last_name = arguments.get("lastName", "").strip()
        # name = f"{first_name} {last_name}"
        phone = arguments.get("phone")
        # branchId =self.g.get("branch").get('id')
        branchId = self.meta.get("branch").get('id')

        print('*****************************************')
     

        # Only missing booking info triggers a prompt
        service = arguments.get("service")
        date = arguments.get("date")
        time = arguments.get("time")

        missing_fields = [
            field for field, value in {
                "service": service,
                "date": date,
                "time": time
            }.items() if not value
        ]

        if missing_fields:
            await params.result_callback({
                "status": "missing_info",
                "message": f"Please provide the following information: {', '.join(missing_fields)}"
            })
            return

        try:
            # Convert date/time to timestamp
            dt = datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M")
            lagos = pytz.timezone("Africa/Lagos")
            timestamp = int(lagos.localize(dt).timestamp())

            # Make booking via MCP
            result = await self.mcp_client.make_branch_booking(
                name=name,
                phone=phone,
                service=service,
                timestamp=timestamp,
                branchId=branchId,
            )

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



    # ---------------------------------------------------------
    # Ensure client is registered
    # ---------------------------------------------------------
    async def ensure_registered(self, params: FunctionCallParams):
        """
        Ensures the client is registered.
        - For registered clients: returns the stored client profile.
        - For unregistered clients: prompts registration.
        - Never prompts for first/last name if client is already registered.
        """
        client = self.meta.get("client")
        is_registered = self.meta.get("is_client_registered", False)

        if is_registered and client:
            # Registered clients are trusted; do not prompt for names
            return client

        # Not registered → prompt for registration
        await params.result_callback({
            "status": "not_registered",
            "message": "I need to register you first. May I have your first and last name?"
        })
        return None


    # ---------------------------------------------------------
    # GET BOOKINGS BY CLIENT
    # ---------------------------------------------------------
    async def get_client_bookings(self, params: FunctionCallParams):
        """
        Fetch client appointments and provide both structured and natural-language output.
        Greets the user, lists all bookings, and ends with a friendly message.
        Converts ISO 8601 dates to "30th (Sunday) of December 2025".
        Converts military time to 12-hour format with AM/PM.
        Includes start and end times in spoken output.
        """
        try:
            # Ensure client is registered
            client = await self.ensure_registered(params)

            # Fetch appointments for the client
            result = await self.mcp_client.get_client_bookings(client['id'])
            appointment_data = result.get("content", {}).get("data", [])

            if not appointment_data:
                await params.result_callback({
                    "status": "success",
                    "services": [],
                    "spoken": "You have no appointments at the moment."
                })
                return

            spoken_text = ["You have the following bookings:"]

            # Helper to convert military time to 12-hour AM/PM
            def format_time(military_time):
                if not military_time:
                    return "Unknown time"
                try:
                    time_str = str(military_time).zfill(4)  # e.g., 900 -> '0900'
                    hour = int(time_str[:2])
                    minute = int(time_str[2:])
                    time_obj = datetime.strptime(f"{hour}:{minute}", "%H:%M")
                    return time_obj.strftime("%I:%M %p").lstrip("0")
                except Exception:
                    return str(military_time)

            # Helper to format date
            def format_date(date_str):
                if not date_str:
                    return "Unknown date"
                try:
                    # Parse only the date part, ignore time and timezone
                    date_obj = datetime.strptime(date_str[:10], "%Y-%m-%d")
                    day = date_obj.day
                    weekday = date_obj.strftime("%A")
                    month = date_obj.strftime("%B")
                    year = date_obj.year

                    # Determine ordinal suffix
                    # if 4 <= day <= 20 or 24 <= day <= 30:
                    #     suffix = "th"
                    # else:
                    #     suffix = ["st", "nd", "rd"][day % 10 - 1]
                    if 4 <= day <= 20 or 24 <= day <= 30:
                        suffix = "th"
                    else:
                        suffix = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")

                    return f"{day}{suffix} ({weekday}) of {month} {year}"
                except Exception:
                    return date_str
                
            # Loop through appointments
            for app in appointment_data:

                description = getattr(app, 'description', None) or app.get('description', 'Unknown service')
                date_str = getattr(app, 'date', None) or app.get('date', None)
                start_time = getattr(app, 'hourStart', None) or  app.get('hourStart')
                end_time = getattr(app, 'hourEnd', None) or  app.get('hourEnd')
                code = getattr(app, 'code', None) or app.get('code', 'N/A')

                formatted_date = format_date(date_str)
                formatted_start = format_time(start_time)
                formatted_end = format_time(end_time)

                # Build spoken text per appointment
                if formatted_end != "Unknown time":
                    spoken_text.append(
                        f"- {description} on {formatted_date} from {formatted_start} to {formatted_end} with booking code: {code}."
                    )
                else:
                    spoken_text.append(
                        f"- {description} on {formatted_date} at {formatted_start} with booking code: {code}."
                    )

            # Add friendly closing
            spoken_text.append("Thank you! Can I help you with something else ?.")

            formatted_text = " ".join(spoken_text)

            await params.result_callback({
                "status": "success",
                "services": appointment_data,
                "spoken": formatted_text
            })

        except Exception as e:
            logger.error(f"Failed to get client bookings: {e}", exc_info=True)
            await params.result_callback({
                "status": "error",
                "message": "Unable to fetch client bookings at this time."
            })
    # ---------------------------------------------------------
    # GET AVAILABILITY BY CLIENT
    # ---------------------------------------------------------
    async def get_client_availability(self, params: FunctionCallParams):
        """
        Fetch client appointments and provide both structured and natural-language output.
        Greets the user, lists all bookings, and ends with a friendly message.
        Converts ISO 8601 dates to "30th (Sunday) of December 2025".
        Converts military time to 12-hour format with AM/PM.
        Includes start and end times in spoken output.
        """
        try:
            # Ensure client is registered
            client = await self.ensure_registered(params)

            # Fetch appointments for the client
            result = await self.mcp_client.get_client_bookings(client['id'])
            appointment_data = result.get("content", {}).get("data", [])

            if not appointment_data:
                await params.result_callback({
                    "status": "success",
                    "services": [],
                    "spoken": "You have no appointments at the moment."
                })
                return

            spoken_text = ["You have the following bookings:"]

            # Helper to convert military time to 12-hour AM/PM
            def format_time(military_time):
                if not military_time:
                    return "Unknown time"
                try:
                    time_str = str(military_time).zfill(4)  # e.g., 900 -> '0900'
                    hour = int(time_str[:2])
                    minute = int(time_str[2:])
                    time_obj = datetime.strptime(f"{hour}:{minute}", "%H:%M")
                    return time_obj.strftime("%I:%M %p").lstrip("0")
                except Exception:
                    return str(military_time)

            # Helper to format date
            def format_date(date_str):
                if not date_str:
                    return "Unknown date"
                try:
                    # Parse only the date part, ignore time and timezone
                    date_obj = datetime.strptime(date_str[:10], "%Y-%m-%d")
                    day = date_obj.day
                    weekday = date_obj.strftime("%A")
                    month = date_obj.strftime("%B")
                    year = date_obj.year

                    # Determine ordinal suffix
                    # if 4 <= day <= 20 or 24 <= day <= 30:
                    #     suffix = "th"
                    # else:
                    #     suffix = ["st", "nd", "rd"][day % 10 - 1]
                    if 4 <= day <= 20 or 24 <= day <= 30:
                        suffix = "th"
                    else:
                        suffix = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")

                    return f"{day}{suffix} ({weekday}) of {month} {year}"
                except Exception:
                    return date_str
                
            # Loop through appointments
            for app in appointment_data:

                description = getattr(app, 'description', None) or app.get('description', 'Unknown service')
                date_str = getattr(app, 'date', None) or app.get('date', None)
                start_time = getattr(app, 'hourStart', None) or  app.get('hourStart')
                end_time = getattr(app, 'hourEnd', None) or  app.get('hourEnd')
                code = getattr(app, 'code', None) or app.get('code', 'N/A')

                formatted_date = format_date(date_str)
                formatted_start = format_time(start_time)
                formatted_end = format_time(end_time)

                # Build spoken text per appointment
                if formatted_end != "Unknown time":
                    spoken_text.append(
                        f"- {description} on {formatted_date} from {formatted_start} to {formatted_end} with booking code: {code}."
                    )
                else:
                    spoken_text.append(
                        f"- {description} on {formatted_date} at {formatted_start} with booking code: {code}."
                    )

            # Add friendly closing
            spoken_text.append("Thank you! Can I help you with something else ?.")

            formatted_text = " ".join(spoken_text)

            await params.result_callback({
                "status": "success",
                "services": appointment_data,
                "spoken": formatted_text
            })

        except Exception as e:
            logger.error(f"Failed to get client bookings: {e}", exc_info=True)
            await params.result_callback({
                "status": "error",
                "message": "Unable to fetch client bookings at this time."
            })
    
    # ---------------------------------------------------------
    # GET BOOKINGS BY BRANCH
    # ---------------------------------------------------------
    async def get_branch_bookings(self, params: FunctionCallParams):
        """
        Fetch client appointments and provide both structured and natural-language output.
        Greets the user, lists all bookings, and ends with a friendly message.
        Converts ISO 8601 dates to "30th (Sunday) of December 2025".
        Converts military time to 12-hour format with AM/PM.
        Includes start and end times in spoken output.
        """
        try:
            # Ensure client is registered
            branchId = self.meta.get("branch").get("id")

            

            # Fetch appointments for the client
            result = await self.mcp_client.get_branch_bookings(branchId)

            appointment_data = result.get("content", {}).get("data", [])

            if not appointment_data:
                await params.result_callback({
                    "status": "success",
                    "services": [],
                    "spoken": "You have no appointments at the moment."
                })
                return

            spoken_text = ["You have the following bookings:"]

            # Helper to convert military time to 12-hour AM/PM
            def format_time(military_time):
                if not military_time:
                    return "Unknown time"
                try:
                    time_str = str(military_time).zfill(4)  # e.g., 900 -> '0900'
                    hour = int(time_str[:2])
                    minute = int(time_str[2:])
                    time_obj = datetime.strptime(f"{hour}:{minute}", "%H:%M")
                    return time_obj.strftime("%I:%M %p").lstrip("0")
                except Exception:
                    return str(military_time)

            # Helper to format date
            def format_date(date_str):
                if not date_str:
                    return "Unknown date"
                try:
                    # Parse only the date part, ignore time and timezone
                    date_obj = datetime.strptime(date_str[:10], "%Y-%m-%d")
                    day = date_obj.day
                    weekday = date_obj.strftime("%A")
                    month = date_obj.strftime("%B")
                    year = date_obj.year

                    # Determine ordinal suffix
                    if 4 <= day <= 20 or 24 <= day <= 30:
                        suffix = "th"
                    else:
                        suffix = ["st", "nd", "rd"][day % 10 - 1]

                    return f"{day}{suffix} ({weekday}) of {month} {year}"
                except Exception:
                    return date_str
                
            # Loop through appointments
            for app in appointment_data:

                description = getattr(app, 'description', None) or app.get('description', 'Unknown service')
                date_str = getattr(app, 'date', None) or app.get('date', None)
                start_time = getattr(app, 'hourStart', None) or  app.get('hourStart')
                end_time = getattr(app, 'hourEnd', None) or  app.get('hourEnd')
                code = getattr(app, 'code', None) or app.get('code', 'N/A')

                client_info = app.get('client') or {}
                client_name = f"{client_info.get('firstName', '')} {client_info.get('lastName', '')}".strip() or app.get('callerName', 'Unknown')

            
                formatted_date = format_date(date_str)
                formatted_start = format_time(start_time)
                formatted_end = format_time(end_time)

                # Build spoken text per appointment
                if formatted_end != "Unknown time":
                    spoken_text.append(
                        f"- {client_name} {description} on {formatted_date} from {formatted_start} to {formatted_end} with booking code: {code}."
                    )
                else:
                    spoken_text.append(
                        f"-{client_name}  {description} on {formatted_date} at {formatted_start} with booking code: {code}."
                    )

            # Add friendly closing
            spoken_text.append("Thank you! Can I help you with something else ?.")

            formatted_text = " ".join(spoken_text)

            await params.result_callback({
                "status": "success",
                "services": appointment_data,
                "spoken": formatted_text
            })

        except Exception as e:
            logger.error(f"Failed to get business bookings: {e}", exc_info=True)
            await params.result_callback({
                "status": "error",
                "message": "Unable to fetch business bookings at this time."
            })
            
    # ---------------------------------------------------------
    # CANCEL BOOKINGS
    # ---------------------------------------------------------
    async def cancel_booking(self, params: FunctionCallParams):

        arguments = params.arguments or {}
        code = arguments.get("code", "")
        reason = arguments.get("reason", "")


        if not code:
            await params.result_callback({"status": "error", "message": "Booking code is required"})
            return

        try:
            result = await self.mcp_client.call_tool("cancel_booking", {"code": code, "reason" : reason, "source" : self.meta['type']})
          
            msg = result.get("content", {}).get("text", "Booking cancelled successfully.")

            await params.result_callback({"status": "success", "message": msg})

        except Exception as e:
            logger.error(f"Failed to cancel booking: {e}")
            await params.result_callback({"status": "error", "message": str(e)})

   
    # ---------------------------------------------------------
    # RESCHEDULE BOOKING
    # ---------------------------------------------------------
    async def update_booking(self, params: FunctionCallParams):
        arguments = params.arguments or {}
        code = arguments.get("code")
        date = arguments.get("date")
        time = arguments.get("time")
        service = arguments.get("service")

        if not code:
            await params.result_callback({"status": "error", "message": "Booking code is required"})
            return

        try:
            result = await self.mcp_client.call_tool("update_booking", {"code": code, "date": date, "time" :  time, "service": service})
            msg = result.get("content", {}).get("text", "Booking updated successfully.")

            await params.result_callback({"status": "success", "message": msg})

        except Exception as e:
            logger.error(f"Failed to cancel booking: {e}")
            await params.result_callback({"status": "error", "message": str(e)})

    # ---------------------------------------------------------
    # GET SERVICES
    # ---------------------------------------------------------
    async def get_services(self, params: FunctionCallParams):
    
        try:
            result = await self.mcp_client.get_services(self.meta['metadata']['recipient'])
            services_data = result.get("content",{}).get("data", {})

            if not services_data:
                await params.result_callback({
                    "status": "success",
                    "services": "No services found."
                })
                return

            # Group services by category
            categories = defaultdict(list)
            for svc in services_data:
                cat = svc.get("category", "Other")
                categories[cat].append(svc)

            # Create natural language output
            spoken_text = []
            for cat, svcs in categories.items():
                service_names = [f"{s['name']} (${s['price']})" for s in svcs]
                # spoken_text.append(f"For {cat}, we offer: {', '.join(service_names)}.")
                spoken_text.append(f"We offer: {', '.join(service_names)}.")

            formatted_text = " ".join(spoken_text)

            # Return both structured and spoken format
            await params.result_callback({
                "status": "success",
                "services": services_data,
                "spoken": formatted_text
            })

        except Exception as e:
            logger.error(f"Failed to get services: {e}")
            await params.result_callback({"status": "error", "message": str(e)})

    def to_ampm(self,hhmm: int) -> str:
        hour = hhmm // 100
        minute = hhmm % 100

        period = "AM" if hour < 12 else "PM"
        hour_12 = hour % 12 or 12

        return f"{hour_12}:{minute:02d} {period}"


    # ---------------------------------------------------------
    # GET branch availability
    # ---------------------------------------------------------
    async def get_availability_branch(self, params: FunctionCallParams):
      
        arguments = params.arguments or {}
        date = arguments.get("date")
        branchId = self.meta.get("branch", {}).get("id")

        try:
            result = await self.mcp_client.call_tool(
                "get_branch_availability_by_reference",
                {"date": date, "branchId": branchId, "branchPhone" : self.meta['metadata']['recipient']}
            )

            content = result.get("content")
            print(content)

            if not content:
                await params.result_callback({
                    "content": [
                        { "type": "text", "text": "All timeslot are open." }
                    ]
                })
            else:
            
                DAY_START = 9   # 9 AM
                DAY_END = 18    # 6 PM

                content = result.get("content", [])

                # 1. Parse unavailable slots
                unavailable = set()

                for item in content:
                    text = item.get("text", "")
                    try:
                        start, end = text.replace(" ", "").split("to")
                        unavailable.add((int(start), int(end)))
                    except ValueError:
                        continue

                # 2. Generate available slots
                available_slots = []

                for hour in range(DAY_START, DAY_END):
                    start = hour * 100
                    end = (hour + 1) * 100

                    if (start, end) not in unavailable:
                        available_slots.append(
                            f"{self.to_ampm(start)} to {self.to_ampm(end)}"
                        )

                # 3. Speak as one message
                if available_slots:
                    message = (
                        "The available time slots for the day are: "
                        + ", ".join(available_slots)
                    )
                else:
                    message = "There are no available time slots for this day."

                await params.result_callback({
                    "content": [
                        { "type": "text", "text": message }
                    ]
                })

        except Exception as e:
            logger.error(f"Failed to get availability: {e}")
            await params.result_callback({
                "status": "error",
                "message": "Unable to retrieve branch availability."
            })



    

    # ---------------------------------------------------------
    # GET Business by phone
    # ---------------------------------------------------------
    async def get_business_by_phone(self, params: FunctionCallParams):
        arguments = params.arguments or {}
        phone = arguments.get("phone", "")

        try:
            result = await self.mcp_client.call_tool("get_business_by_phone", {"phone": phone})
            msg = result.get("content", {}).get("text", "No services found.")
            await params.result_callback({"status": "success", "services": msg})

        except Exception as e:
            logger.error(f"Failed to get services: {e}")
            await params.result_callback({"status": "error", "message": str(e)})

    async def fetch_business_by_phone(self, phone: str):
        """Direct call that bypasses Gemini and returns business data."""
        try:
            result = await self.mcp_client.get_business_by_phone(phone)
            data = result.get("content", {}).get("data", "")
            
            return data
            
        except Exception as e:
            logger.error(f"Failed direct get_business_by_phone: {e}")
            return {
                "status": "error",
                "message": str(e)
            }
    
    async def get_branch_by_reference(self, reference: str):
        """Direct call that bypasses Gemini and returns business data."""
        try:
            result = await self.mcp_client.get_branch_by_reference(reference)
            data = result.get("content", {}).get("data", "")
            
            return data
            
        except Exception as e:
            logger.error(f"Failed direct get_business_by_phone: {e}")
            return {
                "status": "error",
                "message": str(e)
            }
    
    # ---------------------------------------------------------
    # Register client
    # ---------------------------------------------------------
    async def register_client(self, params: FunctionCallParams):
        """
        Registers a new client, updates `meta`, sends a personalized greeting,
        and automatically continues with booking if booking info is provided.
        """
        args = params.arguments or {}
        firstName = args.get("firstName")
        lastName = args.get("lastName")
        phone = self.meta['metadata']['caller']

        try:
            # Register the client in MCP
            await self.mcp_client.register_client(
                firstName=firstName,
                lastName=lastName,
                phone=phone,
            )


            result = await self.mcp_client.get_client_by_phone(phone)
            # Update meta to mark client as registered
            client_data = result.get("content", {}).get("data", {})
            self.meta["client"] = client_data
            self.meta["is_client_registered"] = True
            # self.meta["is_client_registered"] = True

            # Send immediate personalized greeting
            greeting_text = f"Hi {firstName} {lastName}! You have successfully registered. I'm Geny, here to help you book your services."
            await params.result_callback({
                "status": "success",
                "message": "Your profile has been created successfully.",
                "client": client_data,
                "greeting": greeting_text
            })

            # Automatically continue booking if booking info exists
            booking_args = args.get("booking") or {}  # Optional dict: service/date/time
            if booking_args:
                logger.info("Automatically continuing with booking after registration...")
                await self.make_client_booking(FunctionCallParams(
                    arguments=booking_args,
                    result_callback=params.result_callback
                ))

        except Exception as e:
            logger.error(f"Client registration failed: {e}")
            await params.result_callback({
                "status": "error",
                "message": str(e)
            })


