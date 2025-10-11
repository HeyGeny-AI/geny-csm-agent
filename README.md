# Conversational Booking Bot with MCP Protocol

A voice-powered appointment booking system that combines Google's Gemini Live conversational AI with the Model Context Protocol (MCP) for seamless appointment management.

## Overview

This project demonstrates a production-ready voice assistant named "Geny" that can:
- Have natural voice conversations with users
- Create and manage appointment bookings
- Query existing bookings by customer name
- Process voice commands in real-time

The system uses a modern architecture that separates concerns between the conversational AI layer and the business logic layer through the MCP protocol.

## Architecture

### Conversational AI Layer
**Gemini 2.5 Flash Native Audio** provides the conversational interface with these key features:

- **Native Audio Processing**: Direct audio-to-audio processing without intermediate text conversion
- **Low Latency**: Real-time voice interactions with minimal delay
- **Function Calling**: Structured tool invocation for booking operations
- **Voice Identity**: Uses the "Charon" voice profile for consistent personality
- **VAD (Voice Activity Detection)**: Silero VAD with 0.5-second stop detection for natural turn-taking

### Transport Layer
**Pipecat Framework** orchestrates the entire conversation pipeline:

```
Audio Input → VAD → Transcription → LLM → Audio Output
                ↓                    ↓
            Transcript           Function Calls
```

Supports multiple transport protocols:
- **Twilio**: For phone-based interactions
- **WebRTC**: For browser-based voice chat

### Business Logic Layer
**MCP (Model Context Protocol)** bridges the AI and application logic:

The system uses a NestJS-based MCP server that exposes booking operations as standardized tools. This architecture provides:

- **Separation of Concerns**: AI logic separate from business rules
- **Standardized Interface**: MCP protocol for tool discovery and invocation
- **Type Safety**: Structured schemas for all tool parameters
- **Scalability**: Easy to add new booking types or services

## MCP Protocol Implementation

### What is MCP?

The Model Context Protocol (MCP) is an open standard for connecting AI models to external tools and data sources. In this implementation, MCP acts as a bridge between Gemini's function calling and your booking backend.

### MCP Client Architecture

The `NestJSMCPClient` provides an HTTP-based interface to the MCP server:

```python
mcp_client = NestJSMCPClient(
    base_url="http://localhost:3004",
    api_key="your-api-key"
)
```

#### Key Operations

**Health Check**
```python
health = await mcp_client.health_check()
# Returns: {"status": "healthy", "tools": [...]}
```

**Tool Discovery**
```python
tools = await mcp_client.list_tools()
# Lists available MCP tools like make_booking, get_bookings
```

**Tool Invocation**
```python
result = await mcp_client.call_tool("make_booking", {
    "name": "John Doe",
    "phone": "+1234567890",
    "service": "Haircut",
    "timestamp": 1728648000
})
```

### MCP Tool Definitions

#### make_booking Tool
Creates a new appointment with validation and conflict checking.

**Parameters:**
- `name` (string): Customer's full name
- `phone` (string): Contact phone number
- `service` (string): Service type (Haircut, Massage, Nails, etc.)
- `date` (string): Date in YYYY-MM-DD format
- `time` (string): Time in HH:MM format (24-hour)

**Returns:**
```json
{
  "status": "success",
  "message": "Booking confirmed for John Doe...",
  "confirmation": {...}
}
```

#### get_bookings Tool
Retrieves existing bookings for a customer.

**Parameters:**
- `name` (string): Customer name to search

**Returns:**
```json
{
  "status": "success",
  "bookings": "Found 2 bookings: 1) Haircut on 2025-10-15..."
}
```

## Function Handler Factory Pattern

The code uses a factory pattern to inject the MCP client into function handlers:

```python
def make_booking_handler_factory(mcp_client: NestJSMCPClient):
    async def make_booking_handler(params: FunctionCallParams):
        # Access mcp_client via closure
        result = await mcp_client.make_booking(...)
        await params.result_callback(result)
    return make_booking_handler

# Register with LLM
llm.register_function(
    "make_booking", 
    make_booking_handler_factory(mcp_client)
)
```

This pattern ensures each function handler has access to the MCP client while maintaining clean separation of concerns.

## Conversation Flow

### Booking Appointment
1. User: "I'd like to book a haircut"
2. Geny: "I'd be happy to help! What's your name?"
3. User: "John Doe"
4. Geny: "Great! What's your phone number?"
5. User: "555-1234"
6. Geny: "When would you like to schedule your haircut?"
7. User: "Next Friday at 2pm"
8. Geny processes date/time → calls `make_booking` via MCP
9. Geny: "Perfect! Your haircut is booked for Friday, October 18th at 2:00 PM"

### Checking Bookings
1. User: "Can you check my appointments?"
2. Geny: "Sure! What name are your bookings under?"
3. User: "John Doe"
4. Geny calls `get_bookings` via MCP
5. Geny: "You have 2 upcoming appointments: Haircut on October 18th..."

## Setup Instructions

### Prerequisites
- Python 3.9+
- NestJS MCP server running
- Google API key for Gemini
- Twilio account (for phone integration) or WebRTC setup

### Environment Variables
```bash
GOOGLE_API_KEY=your_gemini_api_key
MCP_SERVER_URL=http://localhost:3004
MCP_API_KEY=your_mcp_api_key
ENV=local  # or production
```

### Installation
```bash
pip install -r requirements.txt
python bot.py
```

### Running Locally
```bash
# Start MCP server first
cd mcp-server && npm run start

# Start bot
python bot.py
```

## Key Features

### Timezone Handling
The system converts human-readable dates/times to Unix timestamps with timezone awareness:

```python
lagos_tz = pytz.timezone('America/Los_Angeles')
dt = lagos_tz.localize(datetime.strptime("2025-10-15 14:00", "%Y-%m-%d %H:%M"))
timestamp = int(dt.timestamp())
```

### Error Handling
Comprehensive error handling at every layer:
- Invalid date/time formats
- Missing required fields
- MCP server connectivity issues
- Booking conflicts

### Session Management
Automatic cleanup of resources:
```python
@transport.event_handler("on_client_disconnected")
async def on_client_disconnected(transport, client):
    await mcp_client.close()  # Clean session termination
```

## Benefits of This Architecture

1. **Modularity**: Easy to swap Gemini for another LLM or add new MCP tools
2. **Testability**: MCP layer can be tested independently
3. **Scalability**: Add new services without touching AI logic
4. **Maintainability**: Clear separation between conversation and business logic
5. **Extensibility**: MCP protocol makes adding new capabilities straightforward

## Future Enhancements

- Add booking cancellation/modification tools
- Support multiple languages through Gemini's multilingual capabilities
- Implement booking reminders via MCP
- Add calendar availability checking
- Support group bookings
- Integration with payment processing

## License

Copyright (c) 2024–2025, Daily  
BSD 2-Clause License

## Contributing

Contributions welcome! Key areas for improvement:
- Additional MCP tools for booking management
- Enhanced error recovery strategies
- Support for more transport protocols
- Improved natural language date/time parsing