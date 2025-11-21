from typing import Optional, Dict, Any
import aiohttp
from loguru import logger

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

