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
    
    async def make_client_booking(self, name: str, phone: str, service: str, timestamp: int, branch_reference: str, clientId: int) -> Dict[str, Any]:
        args = {"name": name, "phone": phone, "service": service, "timestamp": timestamp, branch_reference: branch_reference, "clientId": clientId}
        logger.info(f"Making booking: {args}")
        return await self.call_tool("make_client_booking", args)
    
    async def make_branch_booking(self, name: str, phone: str, service: str, timestamp: int, branchId: int) -> Dict[str, Any]:
        args = {"name": name, "phone": phone, "service": service, "timestamp": timestamp, "branchId": branchId}
        logger.info(f"Making booking: {args}")
        return await self.call_tool("make_branch_booking", args)
    
    async def get_branch_bookings(self, branchId: str) -> Dict[str, Any]:
        args = {"branchId": branchId}
        logger.info(f"Getting bookings for: {branchId}")
        return await self.call_tool("get_branch_bookings", args)
    
    async def get_client_bookings(self, clientId: int) -> Dict[str, Any]:
        args = {"clientId": clientId}
        logger.info(f"Getting bookings for: {clientId}")
        return await self.call_tool("get_client_bookings", args)
    
    async def get_services(self, genyPhone: str) -> Dict[str, Any]:
        args = {"reference": genyPhone}
        logger.info(f"Getting bookings for: {genyPhone}")
        return await self.call_tool("get_services", args)
    
    async def get_business_by_phone(self, phone: str) -> Dict[str, Any]:
        args = {"phone": phone}
        logger.info(f"Getting business: {phone}")
        return await self.call_tool("get_business_by_phone", args)
    
    async def get_branch_by_reference(self, reference: str) -> Dict[str, Any]:
        args = {"reference": reference}
        logger.info(f"Getting branch: {reference}")
        return await self.call_tool("get_branch_by_reference", args)
    
    async def cancel_booking(self, code: str) -> Dict[str, Any]:
        args = {"code": code}
        logger.info(f"Booking code: {code}")
        return await self.call_tool("cancel_booking", args)
    
    async def get_client_by_phone(self, phone: str):
        return await self.call_tool("get_client_by_phone", {"phone": phone})
    

    async def register_client(self, firstName: str, lastName: str, phone: str) -> Dict[str, Any]:
        args = {"phone": phone, "firstName": firstName, "lastName" : lastName}
        logger.info(f"register client")
        return await self.call_tool("register_client", args)


