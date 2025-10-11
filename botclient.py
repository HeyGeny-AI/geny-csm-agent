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