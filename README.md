# Geny Voice Receptionist  
*A conversational booking assistant built with Gemini 2.5 Flash, Pipecat, and the Model Context Protocol (MCP).*

---

## What is this?

**Geny Voice Receptionist** is a voice-powered assistant that answers calls and messages for busy service professionals — like nail techs, barbers, or estheticians — so they never miss a client.

When a client calls or texts, Geny picks up instantly, speaks naturally, and can:
- Check prices or available services  
- Book or reschedule appointments  
- Take messages for review later  

After each interaction, Geny sends a short **voice summary** to the business owner:  
> “Jasmine booked a nail refill for 2 PM tomorrow.”

This project demonstrates a **production-ready, real-time conversational pipeline** powered by **Gemini** and **Pipecat**, connected to a structured booking backend via the **Model Context Protocol (MCP)**.

---

## A video (less than 60 seconds)

**[Demo Video → Add link here after upload]**

*(The demo should show: incoming call → Geny responds → booking confirmation → owner voice summary.)*

---

## Describe how you used Gemini models and Pipecat

**Gemini** and **Pipecat** form the conversational intelligence and transport backbone of Geny.

### Gemini 2.5 Flash Native Audio
- Provides end-to-end **speech-to-speech reasoning** for natural voice conversation.  
- Handles intent detection (e.g., “check price,” “book appointment,” “leave message”).  
- Executes **function calls** to MCP tools for structured booking actions.  
- Synthesizes real-time, low-latency speech responses.  

### Pipecat Framework
- Orchestrates the full pipeline:


```
Audio Input → VAD → Transcription → LLM → Audio Output
                ↓                    ↓
            Transcript           Function Calls
```

- Supports multiple transports (Twilio for phone, WebRTC for browser-based voice).  
- Manages the **streaming connection**, message turn-taking, and latency tracing.  

Together, Gemini and Pipecat enable Geny to act as a **fully autonomous voice receptionist** with real-time comprehension and response.

---

## Describe other tools you used

| Tool | Role |
|------|------|
| **Model Context Protocol (MCP)** | Bridges Gemini’s function calls with backend booking logic (implemented via a NestJS MCP server). |
| **Twilio (Pipecat Transports)** | Enables live call and browser voice connections. |
| **ElevenLabs** | Provides the branded “Geny” voice for consistent identity. |
| **FastAPI / Python 3.9** | Powers the conversational layer and MCP client. |

---

## Tell us what you did new during the hackathon

During the hackathon, we extended our existing MCP booking assistant into a **real-time voice receptionist** by integrating Gemini and Pipecat.

### 🚀 New Components Built:
- **Gemini × Pipecat 3-model speech loop** for natural speech-to-speech interaction.  
- **Busy Mode trigger** that activates when the owner is serving a client.  
- New **Gemini function calls** for:
- `check_price`
- `book_appointment`
- `leave_message`
- **Voice summary generator** to provide the business owner with short audio recaps.  

These additions transformed the project from a booking demo into a **fully conversational receptionist** capable of real-time, hands-free operation.

---

## Give feedback on the tools you used

| Tool | What worked well | What could improve |
|------|------------------|--------------------|
| **Gemini 2.5 Flash** | Excellent at real-time reasoning and context retention. | Occasional delays in transcription under background noise. |
| **Pipecat** | Beautifully modular and simple to extend with transports. | More examples for Twilio routing would speed up setup. |
| **MCP Protocol** | Clean separation between AI and backend business logic. | A Python-native SDK would simplify client development. |

Overall, the stack was remarkably fast to integrate — we were able to get from idea to live demo in under 5 hours.

---
### 👩🏽‍💻 Credits  
Built by the **Geny Labs** team — a global group developing AI assistants for skilled-service entrepreneurs.  

**License:** BSD 2-Clause © 2025 Daily & Geny Labs Inc.  

