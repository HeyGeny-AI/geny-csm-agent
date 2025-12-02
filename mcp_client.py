import aiohttp
from loguru import logger
from typing import Dict, Any, Optional


class NestJSMCPClient:
    """
    A corrected, safe, leak-proof MCP API client for NestJS backend.
    Ensures:
    - One shared session per call lifecycle
    - No implicit connector creation
    - Safe closing of sessions
    """

    def __init__(self, base_url: str, token: Optional[str] = None):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.session: Optional[aiohttp.ClientSession] = None

    # ---------------------------------------------------------
    # INTERNAL HELPERS
    # ---------------------------------------------------------
    async def _ensure_session(self):
        if self.session is None or self.session.closed:
            logger.debug("Creating new aiohttp session for MCP client.")
            self.session = aiohttp.ClientSession()

    def _headers(self):
        h = {"Content-Type": "application/json"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    async def _post(self, path: str, payload: Dict[str, Any]):
        await self._ensure_session()
        url = f"{self.base_url}{path}"

        try:
            async with self.session.post(url, json=payload, headers=self._headers()) as resp:
                resp.raise_for_status()
                return await resp.json()
        except Exception as e:
            logger.error(f"MCP POST {path} failed: {e}")
            raise

    async def close(self):
        if self.session and not self.session.closed:
            logger.debug("Closing MCP aiohttp session gracefully.")
            await self.session.close()

    # ---------------------------------------------------------
    # PUBLIC METHODS (TOOLS)
    # ---------------------------------------------------------

    async def call_tool(self, tool_name: str, args: Dict[str, Any]):
        payload = {"name": tool_name, "args": args}
        return await self._post("/mcp/call-tool", payload)

    # BOOKING: CLIENT
    async def make_client_booking(self, name, phone, service, timestamp, branch_reference, clientId):
        return await self.call_tool("make_client_booking", {
            "name": name,
            "phone": phone,
            "service": service,
            "timestamp": timestamp,
            "branch_reference": branch_reference,
            "clientId": clientId,
        })

    # BOOKING: BRANCH
    async def make_branch_booking(self, name, phone, service, timestamp, branchId):
        return await self.call_tool("make_branch_booking", {
            "name": name,
            "phone": phone,
            "service": service,
            "timestamp": timestamp,
            "branchId": branchId,
        })

    async def get_client_bookings(self, client_id):
        return await self.call_tool("get_client_bookings", {"clientId": client_id})

    async def get_branch_bookings(self, branch_id):
        return await self.call_tool("get_branch_bookings", {"branchId": branch_id})

    async def get_services(self, branch_reference):
        return await self.call_tool("get_services", {"reference": branch_reference})

    async def register_client(self, firstName, lastName, phone):
        return await self.call_tool("register_client", {
            "firstName": firstName,
            "lastName": lastName,
            "phone": phone,
        })

    async def get_client_by_phone(self, phone):
        return await self.call_tool("get_client_by_phone", {"phone": phone})

    async def get_business_by_phone(self, phone):
        return await self.call_tool("get_business_by_phone", {"phone": phone})

    async def get_branch_by_reference(self, reference):
        return await self.call_tool("get_branch_by_reference", {"reference": reference})
