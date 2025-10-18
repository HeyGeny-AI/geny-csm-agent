import os
import argparse
import asyncio
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse
from loguru import logger

# Load API keys from env
from dotenv import load_dotenv
load_dotenv(override=True)

# Configure logging to suppress the specific KeyError
import logging

# Create a custom filter to suppress KeyError messages from Pipecat WebSocket transport
class PipecatKeyErrorFilter(logging.Filter):
    """Filter out KeyError messages from Pipecat WebSocket transport."""
    def filter(self, record):
        # Suppress KeyError messages related to 'text' field in WebSocket transport
        if "KeyError" in record.getMessage() and "'text'" in record.getMessage():
            return False
        return True

# Apply filter to Pipecat WebSocket logger
pipecat_ws_logger = logging.getLogger('pipecat.transports.websocket.fastapi')
pipecat_ws_logger.addFilter(PipecatKeyErrorFilter())
pipecat_ws_logger.setLevel(logging.WARNING)

# Import necessary Pipecat components
from pipecat.transports.websocket.fastapi import FastAPIWebsocketTransport, FastAPIWebsocketParams
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams

# Import your bot's run_bot function
from bot import run_bot


# ------------ Configuration ------------ #

# List of required env vars for the booking bot
REQUIRED_ENV_VARS = [
    'GOOGLE_API_KEY',  # For Gemini Live
    'MCP_SERVER_URL',  # NestJS MCP server URL
]

# Optional env vars
OPTIONAL_ENV_VARS = [
    'MCP_API_KEY',  # API key for MCP server (if required)
]


# ----------------- API ----------------- #

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)


# ----------------- WebSocket Handler ----------------- #

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for bot connections."""
    await websocket.accept()
    logger.info("🔌 WebSocket connection accepted")
    
    transport = None
    
    try:
        # Check for Krisp filter
        krisp_filter = None
        if os.environ.get("ENV") != "local":
            try:
                from pipecat.audio.filters.krisp_filter import KrispFilter
                krisp_filter = KrispFilter()
                logger.info("✓ KrispFilter enabled")
            except ImportError:
                logger.warning("⚠ KrispFilter not available")
        
        # Create transport params
        params = FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_in_filter=krisp_filter,
            audio_out_enabled=True,
            vad_analyzer=SileroVADAnalyzer(params=VADParams(stop_secs=0.5)),
            audio_in_sample_rate=16000,
            audio_out_sample_rate=24000,
        )
        
        # Create transport
        transport = FastAPIWebsocketTransport(
            websocket=websocket,
            params=params
        )
        
        # Create runner arguments
        class RunnerArgs:
            def __init__(self):
                self.handle_sigint = False
                self.pipeline_idle_timeout_secs = 300
        
        runner_args = RunnerArgs()
        
        logger.info("🤖 Starting bot session...")
        
        # Run the bot
        await run_bot(transport, runner_args)
        
    except WebSocketDisconnect:
        logger.info("👋 WebSocket disconnected normally")
    except asyncio.CancelledError:
        logger.info("🛑 WebSocket task cancelled")
    except Exception as e:
        # Don't close on the KeyError - it's a Pipecat internal issue
        if "'text'" in str(e):
            logger.debug("Pipecat text parsing issue (non-fatal)")
        else:
            logger.error(f"❌ WebSocket error: {type(e).__name__}: {e}")
            logger.exception(e)
    finally:
        try:
            if transport:
                logger.debug("Cleaning up transport...")
            if websocket.client_state != websocket.client_state.DISCONNECTED:
                await websocket.close()
        except Exception as cleanup_error:
            logger.debug(f"Cleanup error: {cleanup_error}")

            
# ----------------- REST Endpoints ----------------- #

@app.get("/")
async def root():
    """Root endpoint with service info."""
    return JSONResponse({
        "service": "booking-bot",
        "status": "running",
        "transport": "websocket",
        "endpoints": {
            "websocket": "/ws",
            "health": "/health",
            "test_client": "/test",
            "start_session": "/start_session"
        },
        "info": "Visit /test for a browser-based test client"
    })


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    env_status = {
        "google_api": bool(os.environ.get("GOOGLE_API_KEY")),
        "mcp_server": bool(os.environ.get("MCP_SERVER_URL")),
        "mcp_api_key": bool(os.environ.get("MCP_API_KEY"))
    }
    
    # Check if all required vars are set
    all_required_set = all(
        os.environ.get(var) for var in REQUIRED_ENV_VARS
    )
    
    return JSONResponse({
        "status": "healthy" if all_required_set else "degraded",
        "service": "booking-bot",
        "transport": "websocket",
        "environment": env_status,
        "mcp_server_url": os.getenv("MCP_SERVER_URL", "not_configured"),
        "ready": all_required_set
    })


@app.post("/start_session")
async def start_session():
    """
    Endpoint to get WebSocket connection info.
    Returns the WebSocket URL for clients to connect to.
    """
    host = os.getenv("HOST", "0.0.0.0")
    port = os.getenv("PORT", "7860")
    
    # Determine the WebSocket URL based on the environment
    ws_protocol = "wss" if os.getenv("USE_SSL", "false").lower() == "true" else "ws"
    
    # If behind a proxy/load balancer, use the public URL
    public_url = os.getenv("PUBLIC_URL")
    if public_url:
        ws_url = f"{ws_protocol}://{public_url}/ws"
    else:
        ws_url = f"{ws_protocol}://{host}:{port}/ws"
    
    return JSONResponse({
        "websocket_url": ws_url,
        "transport": "websocket",
        "max_duration_secs": 300,
        "audio_format": {
            "input_sample_rate": 16000,
            "output_sample_rate": 24000,
            "encoding": "pcm16"
        }
    })


@app.get("/test")
async def test_page():
    """Enhanced test page with proper audio handling and visualization."""
    
    html_content = """<!DOCTYPE html>
<html>
<head>
    <title>Geny - Booking Bot</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { 
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif;
            max-width: 900px; 
            margin: 0 auto; 
            padding: 20px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
        }
        .container {
            background: white;
            padding: 30px;
            border-radius: 15px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
        }
        h1 {
            color: #333;
            margin-bottom: 10px;
            font-size: 28px;
        }
        .subtitle {
            color: #666;
            margin-bottom: 30px;
            font-size: 14px;
        }
        button { 
            padding: 12px 24px; 
            margin: 5px; 
            font-size: 16px; 
            cursor: pointer;
            border: none;
            border-radius: 8px;
            transition: all 0.3s;
            font-weight: 600;
        }
        button:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }
        .btn-primary {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
        }
        .btn-primary:hover:not(:disabled) {
            transform: translateY(-2px);
            box-shadow: 0 5px 15px rgba(102, 126, 234, 0.4);
        }
        .btn-danger {
            background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
            color: white;
        }
        .btn-danger:hover:not(:disabled) {
            transform: translateY(-2px);
            box-shadow: 0 5px 15px rgba(245, 87, 108, 0.4);
        }
        .btn-success {
            background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%);
            color: white;
        }
        .btn-success:hover:not(:disabled) {
            transform: translateY(-2px);
            box-shadow: 0 5px 15px rgba(79, 172, 254, 0.4);
        }
        #status { 
            padding: 15px 20px; 
            margin: 20px 0; 
            border-radius: 10px;
            font-weight: 600;
            display: flex;
            align-items: center;
        }
        .connected { 
            background: linear-gradient(135deg, #d4edda 0%, #c3e6cb 100%);
            color: #155724;
        }
        .disconnected { 
            background: linear-gradient(135deg, #f8d7da 0%, #f5c6cb 100%);
            color: #721c24;
        }
        .recording {
            background: linear-gradient(135deg, #fff3cd 0%, #ffeeba 100%);
            color: #856404;
        }
        #messages { 
            border: 2px solid #e0e0e0; 
            padding: 15px; 
            height: 400px; 
            overflow-y: auto; 
            margin: 20px 0;
            background: #fafafa;
            border-radius: 10px;
        }
        .message { 
            margin: 10px 0; 
            padding: 12px 15px;
            border-radius: 8px;
            line-height: 1.6;
            animation: slideIn 0.3s ease;
        }
        @keyframes slideIn {
            from { opacity: 0; transform: translateY(10px); }
            to { opacity: 1; transform: translateY(0); }
        }
        .user { 
            background: linear-gradient(135deg, #e3f2fd 0%, #bbdefb 100%);
            border-left: 4px solid #2196F3;
        }
        .bot { 
            background: linear-gradient(135deg, #e8f5e9 0%, #c8e6c9 100%);
            border-left: 4px solid #4CAF50;
        }
        .system { 
            background: linear-gradient(135deg, #fff3e0 0%, #ffe0b2 100%);
            border-left: 4px solid #FF9800;
            font-style: italic;
            font-size: 14px;
        }
        .error {
            background: linear-gradient(135deg, #ffebee 0%, #ffcdd2 100%);
            border-left: 4px solid #f44336;
        }
        .controls {
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
            margin: 20px 0;
        }
        .indicator {
            display: inline-block;
            width: 12px;
            height: 12px;
            border-radius: 50%;
            margin-right: 10px;
        }
        .indicator.active {
            background-color: #4CAF50;
            animation: pulse 1.5s infinite;
            box-shadow: 0 0 10px #4CAF50;
        }
        .indicator.inactive {
            background-color: #ccc;
        }
        @keyframes pulse {
            0%, 100% { opacity: 1; transform: scale(1); }
            50% { opacity: 0.6; transform: scale(1.1); }
        }
        #audioLevel {
            width: 100%;
            height: 40px;
            margin: 15px 0;
            border-radius: 8px;
            background: #f0f0f0;
        }
        .timestamp {
            font-size: 12px;
            color: #666;
            margin-right: 8px;
        }
        ::-webkit-scrollbar {
            width: 8px;
        }
        ::-webkit-scrollbar-track {
            background: #f1f1f1;
            border-radius: 10px;
        }
        ::-webkit-scrollbar-thumb {
            background: #888;
            border-radius: 10px;
        }
        ::-webkit-scrollbar-thumb:hover {
            background: #555;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🤖 Geny - Booking Assistant</h1>
        <p class="subtitle">Your AI-powered booking assistant</p>
        
        <div id="status" class="disconnected">
            <span class="indicator inactive"></span>
            Disconnected
        </div>
        
        <div class="controls">
            <button id="connectBtn" class="btn-primary" onclick="connect()">
                🔌 Connect to Geny
            </button>
            <button id="disconnectBtn" class="btn-danger" onclick="disconnect()" disabled>
                ⏹ Disconnect
            </button>
            <button id="recordBtn" class="btn-success" onclick="startRecording()" disabled>
                🎤 Start Speaking
            </button>
            <button id="stopBtn" class="btn-danger" onclick="stopRecording()" disabled>
                ⏸ Stop Speaking
            </button>
        </div>

        <canvas id="audioLevel"></canvas>
        
        <div id="messages"></div>
    </div>
    
    <script>
        let ws = null;
        let audioStream = null;
        let audioContext = null;
        let audioSource = null;
        let scriptProcessor = null;
        let audioQueue = [];
        let isPlaying = false;
        let visualizerContext = null;
        let analyser = null;
        let animationFrameId = null;
        
        const canvas = document.getElementById('audioLevel');
        visualizerContext = canvas.getContext('2d');
        canvas.width = canvas.offsetWidth;
        canvas.height = 40;
        
        function log(message, type = 'system') {
            const messagesDiv = document.getElementById('messages');
            const msgDiv = document.createElement('div');
            msgDiv.className = 'message ' + type;
            const timestamp = new Date().toLocaleTimeString();
            msgDiv.innerHTML = '<span class="timestamp">' + timestamp + '</span>' + message;
            messagesDiv.appendChild(msgDiv);
            messagesDiv.scrollTop = messagesDiv.scrollHeight;
        }
        
        function updateStatus(text, className) {
            const statusDiv = document.getElementById('status');
            statusDiv.className = className;
            const isActive = className === 'connected' || className === 'recording';
            statusDiv.innerHTML = '<span class="indicator ' + (isActive ? 'active' : 'inactive') + '"></span>' + text;
        }
        
        function visualizeAudio() {
            if (!analyser || !visualizerContext) return;
            
            const dataArray = new Uint8Array(analyser.frequencyBinCount);
            analyser.getByteFrequencyData(dataArray);
            
            visualizerContext.fillStyle = '#f5f5f5';
            visualizerContext.fillRect(0, 0, canvas.width, canvas.height);
            
            const gradient = visualizerContext.createLinearGradient(0, 0, 0, canvas.height);
            gradient.addColorStop(0, '#4facfe');
            gradient.addColorStop(1, '#00f2fe');
            visualizerContext.fillStyle = gradient;
            
            const barWidth = canvas.width / dataArray.length;
            
            for (let i = 0; i < dataArray.length; i++) {
                const barHeight = (dataArray[i] / 255) * canvas.height;
                visualizerContext.fillRect(i * barWidth, canvas.height - barHeight, barWidth - 1, barHeight);
            }
            
            animationFrameId = requestAnimationFrame(visualizeAudio);
        }
        
        async function connect() {
            try {
                const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
                const wsUrl = protocol + '//' + window.location.host + '/ws';
                
                log('🔄 Connecting to ' + wsUrl + '...', 'system');
                ws = new WebSocket(wsUrl);
                ws.binaryType = 'arraybuffer';
                
                ws.onopen = () => {
                    log('✅ Connected successfully! Click "Start Speaking" when ready.', 'system');
                    updateStatus('✓ Connected - Ready to talk', 'connected');
                    document.getElementById('connectBtn').disabled = true;
                    document.getElementById('disconnectBtn').disabled = false;
                    document.getElementById('recordBtn').disabled = false;
                };
                
                ws.onmessage = async (event) => {
                    if (event.data instanceof ArrayBuffer) {
                        // Binary audio data from bot
                        await playAudioChunk(event.data);
                    } else {
                        // Text message from bot
                        try {
                            const data = JSON.parse(event.data);
                            if (data.type === 'transcript' || data.text) {
                                log('🤖 <strong>Geny:</strong> ' + (data.text || data.content), 'bot');
                            } else if (data.type === 'error') {
                                log('❌ Error: ' + (data.message || JSON.stringify(data)), 'error');
                            } else {
                                log('📋 ' + JSON.stringify(data), 'system');
                            }
                        } catch (e) {
                            if (event.data.trim()) {
                                log('🤖 <strong>Geny:</strong> ' + event.data, 'bot');
                            }
                        }
                    }
                };
                
                ws.onerror = (error) => {
                    log('❌ Connection error occurred', 'error');
                    console.error('WebSocket error:', error);
                };
                
                ws.onclose = (event) => {
                    log('👋 Disconnected from Geny' + (event.reason ? ': ' + event.reason : ''), 'system');
                    updateStatus('✗ Disconnected', 'disconnected');
                    document.getElementById('connectBtn').disabled = false;
                    document.getElementById('disconnectBtn').disabled = true;
                    document.getElementById('recordBtn').disabled = true;
                    document.getElementById('stopBtn').disabled = true;
                    
                    stopRecording();
                };
            } catch (error) {
                log('❌ Failed to connect: ' + error.message, 'error');
                console.error('Connection error:', error);
            }
        }
        
        function disconnect() {
            if (ws) {
                ws.close();
                ws = null;
            }
            stopRecording();
        }
        
        async function startRecording() {
            try {
                log('🎤 Requesting microphone access...', 'user');
                
                audioStream = await navigator.mediaDevices.getUserMedia({ 
                    audio: {
                        echoCancellation: true,
                        noiseSuppression: true,
                        autoGainControl: true,
                        sampleRate: 16000
                    } 
                });
                
                audioContext = new (window.AudioContext || window.webkitAudioContext)({
                    sampleRate: 16000
                });
                
                audioSource = audioContext.createMediaStreamSource(audioStream);
                analyser = audioContext.createAnalyser();
                analyser.fftSize = 256;
                analyser.smoothingTimeConstant = 0.8;
                audioSource.connect(analyser);
                
                scriptProcessor = audioContext.createScriptProcessor(4096, 1, 1);
                
                scriptProcessor.onaudioprocess = (e) => {
                    if (ws && ws.readyState === WebSocket.OPEN) {
                        const inputData = e.inputBuffer.getChannelData(0);
                        
                        // Convert Float32 to Int16 PCM
                        const pcmData = new Int16Array(inputData.length);
                        for (let i = 0; i < inputData.length; i++) {
                            const s = Math.max(-1, Math.min(1, inputData[i]));
                            pcmData[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
                        }
                        
                        // Send as ArrayBuffer (this is the correct format)
                        try {
                            ws.send(pcmData.buffer);
                        } catch (err) {
                            console.error('Error sending audio:', err);
                        }
                    }
                };
                
                audioSource.connect(scriptProcessor);
                scriptProcessor.connect(audioContext.destination);
                
                // Start visualization
                visualizeAudio();
                
                document.getElementById('recordBtn').disabled = true;
                document.getElementById('stopBtn').disabled = false;
                updateStatus('🎤 Recording - Speak now!', 'recording');
                log('✅ Recording started - Geny is listening', 'user');
                
            } catch (err) {
                log('❌ Microphone access denied: ' + err.message, 'error');
                console.error('Microphone error:', err);
            }
        }
        
        function stopRecording() {
            if (audioStream) {
                audioStream.getTracks().forEach(track => track.stop());
                audioStream = null;
            }
            
            if (scriptProcessor) {
                scriptProcessor.disconnect();
                scriptProcessor = null;
            }
            
            if (audioSource) {
                audioSource.disconnect();
                audioSource = null;
            }
            
            if (audioContext && audioContext.state !== 'closed') {
                audioContext.close();
                audioContext = null;
            }
            
            if (animationFrameId) {
                cancelAnimationFrame(animationFrameId);
                animationFrameId = null;
            }
            
            analyser = null;
            
            document.getElementById('recordBtn').disabled = false;
            document.getElementById('stopBtn').disabled = true;
            
            if (ws && ws.readyState === WebSocket.OPEN) {
                updateStatus('✓ Connected - Ready to talk', 'connected');
                log('⏸ Recording stopped', 'user');
            }
            
            // Clear visualizer
            if (visualizerContext) {
                visualizerContext.fillStyle = '#f5f5f5';
                visualizerContext.fillRect(0, 0, canvas.width, canvas.height);
            }
        }
        
        async function playAudioChunk(arrayBuffer) {
            audioQueue.push(arrayBuffer);
            if (!isPlaying) {
                await processAudioQueue();
            }
        }
        
        async function processAudioQueue() {
            if (audioQueue.length === 0) {
                isPlaying = false;
                return;
            }
            
            isPlaying = true;
            const chunk = audioQueue.shift();
            
            try {
                const audioCtx = new (window.AudioContext || window.webkitAudioContext)({
                    sampleRate: 24000
                });
                
                const audioBuffer = await audioCtx.decodeAudioData(chunk);
                const source = audioCtx.createBufferSource();
                source.buffer = audioBuffer;
                source.connect(audioCtx.destination);
                
                source.onended = () => {
                    audioCtx.close();
                    processAudioQueue();
                };
                
                source.start(0);
            } catch (err) {
                console.error('Audio playback error:', err);
                processAudioQueue();
            }
        }
        
        window.addEventListener('beforeunload', () => {
            if (ws) {
                ws.close();
            }
            stopRecording();
        });
        
        log('👋 Welcome! Click "Connect to Geny" to start chatting.', 'system');
    </script>
</body>
</html>"""
    
    return HTMLResponse(content=html_content)


# ----------------- Main ----------------- #

if __name__ == "__main__":
    # Check for required environment variables
    missing_vars = []
    for env_var in REQUIRED_ENV_VARS:
        if env_var not in os.environ:
            missing_vars.append(env_var)
    
    if missing_vars:
        logger.error(f"❌ Missing required environment variables: {', '.join(missing_vars)}")
        raise Exception(f"Missing required environment variables: {', '.join(missing_vars)}")
    
    # Warn about optional environment variables
    for env_var in OPTIONAL_ENV_VARS:
        if env_var not in os.environ:
            logger.warning(f"⚠️  Optional environment variable not set: {env_var}")

    parser = argparse.ArgumentParser(description="Geny - Pipecat Booking Bot")
    parser.add_argument("--host", type=str,
                        default=os.getenv("HOST", "0.0.0.0"), help="Host address")
    parser.add_argument("--port", type=int,
                        default=int(os.getenv("PORT", "7860")), help="Port number")
    parser.add_argument("--reload", action="store_true",
                        default=False, help="Reload code on change")

    config = parser.parse_args()

    try:
        import uvicorn

        logger.info("=" * 60)
        logger.info("🚀 Starting Geny - Booking Bot Runner")
        logger.info("=" * 60)
        logger.info(f"📡 Server: http://{config.host}:{config.port}")
        logger.info(f"🔌 WebSocket: ws://{config.host}:{config.port}/ws")
        logger.info(f"🧪 Test Client: http://{config.host}:{config.port}/test")
        logger.info(f"📋 MCP Server: {os.getenv('MCP_SERVER_URL', 'Not configured')}")
        logger.info(f"🔑 Google API: {'Configured' if os.getenv('GOOGLE_API_KEY') else 'Missing'}")
        logger.info("=" * 60)
        
        uvicorn.run(
            "runner:app",
            host=config.host,
            port=config.port,
            reload=config.reload,
            log_level="info"
        )

    except KeyboardInterrupt:
        logger.info("\n🛑 Shutting down Geny booking bot...")
    except Exception as e:
        logger.error(f"❌ Failed to start server: {e}")
        raise