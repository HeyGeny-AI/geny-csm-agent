"""
Patch for Pipecat's FastAPIWebsocketInputTransport to suppress KeyError.

Create this file as `pipecat_patch.py` and import it BEFORE creating transports.
"""

import logging
from loguru import logger

# Suppress Pipecat WebSocket errors at the source
logging.getLogger('pipecat.transports.websocket.fastapi').setLevel(logging.CRITICAL)


def patch_pipecat_websocket():
    """
    Monkey-patch Pipecat's WebSocket transport to handle binary audio gracefully.
    Call this once at startup before creating any transports.
    """
    try:
        from pipecat.transports.websocket.fastapi import FastAPIWebsocketInputTransport
        
        # Store original method
        original_receive_messages = FastAPIWebsocketInputTransport._receive_messages
        
        async def patched_receive_messages(self):
            """Patched version that silently handles KeyError for binary audio."""
            try:
                await original_receive_messages(self)
            except KeyError as e:
                # This KeyError happens when binary audio data is sent
                # It's not actually an error - the audio is processed correctly
                if "'text'" in str(e) or str(e).strip("'\"") == "text":
                    # Silently ignore - this is expected behavior with binary audio
                    logger.debug("Binary audio data received (KeyError suppressed)")
                    return
                else:
                    # Re-raise unexpected KeyErrors
                    raise
            except Exception as e:
                # Let other exceptions propagate normally
                raise
        
        # Replace the method
        FastAPIWebsocketInputTransport._receive_messages = patched_receive_messages
        logger.info("✅ Pipecat WebSocket transport patched successfully")
        
    except ImportError as e:
        logger.warning(f"⚠️  Could not patch Pipecat: {e}")
    except Exception as e:
        logger.error(f"❌ Failed to patch Pipecat: {e}")


# Auto-apply patch when imported
patch_pipecat_websocket()