from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel
from typing import Optional
import hmac
import hashlib
import time
import httpx
import os

app = FastAPI(title="Binance Testnet Middleware")

# --- Config (set these as environment variables on your hosting platform) ---
API_KEY = os.environ.get("BINANCE_API_KEY", "YOUR_TESTNET_API_KEY")
API_SECRET = os.environ.get("BINANCE_API_SECRET", "YOUR_TESTNET_API_SECRET")
AGENT_TOKEN = os.environ.get("AGENT_TOKEN", "my-secret-agent-token")  # shared secret with your agent

BINANCE_TESTNET_URL = "https://testnet.binancefuture.com"

# ------------------------------------------------------------------ #

def sign(params: dict) -> str:
    """Create HMAC SHA256 signature required by Binance."""
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return hmac.new(API_SECRET.encode(), query.encode(), hashlib.sha256).hexdigest()


# ------------------------------------------------------------------ #
# Request / Response models
# ------------------------------------------------------------------ #

class OrderRequest(BaseModel):
    symbol: str          # e.g. "BTCUSDT"
    side: str            # "BUY" or "SELL"
    order_type: str      # "MARKET" or "LIMIT"
    quantity: float      # e.g. 0.001
    price: Optional[float] = None   # required for LIMIT orders


class AccountRequest(BaseModel):
    pass  # no body needed


# ------------------------------------------------------------------ #
# Routes
# ------------------------------------------------------------------ #

@app.get("/")
def health():
    return {"status": "ok", "message": "Binance Testnet Middleware is running"}


@app.post("/order")
async def place_order(order: OrderRequest, x_agent_token: str = Header(...)):
    """Place a futures order on Binance testnet."""

    # 1. Authenticate the agent
    if x_agent_token != AGENT_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")

    # 2. Build params
    params = {
        "symbol": order.symbol.upper(),
        "side": order.side.upper(),
        "type": order.order_type.upper(),
        "quantity": order.quantity,
        "timestamp": int(time.time() * 1000),
    }

    if order.order_type.upper() == "LIMIT":
        if not order.price:
            raise HTTPException(status_code=400, detail="Price is required for LIMIT orders")
        params["price"] = order.price
        params["timeInForce"] = "GTC"

    # 3. Sign & send to Binance testnet
    params["signature"] = sign(params)

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{BINANCE_TESTNET_URL}/fapi/v1/order",
            params=params,
            headers={"X-MBX-APIKEY": API_KEY},
        )

    if response.status_code != 200:
        raise HTTPException(status_code=response.status_code, detail=response.json())

    return response.json()


@app.get("/balance")
async def get_balance(x_agent_token: str = Header(...)):
    """Get testnet account balance."""

    if x_agent_token != AGENT_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")

    params = {"timestamp": int(time.time() * 1000)}
    params["signature"] = sign(params)

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{BINANCE_TESTNET_URL}/fapi/v2/balance",
            params=params,
            headers={"X-MBX-APIKEY": API_KEY},
        )

    if response.status_code != 200:
        raise HTTPException(status_code=response.status_code, detail=response.json())

    return response.json()


@app.get("/positions")
async def get_positions(x_agent_token: str = Header(...)):
    """Get open positions on testnet."""

    if x_agent_token != AGENT_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")

    params = {"timestamp": int(time.time() * 1000)}
    params["signature"] = sign(params)

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{BINANCE_TESTNET_URL}/fapi/v2/positionRisk",
            params=params,
            headers={"X-MBX-APIKEY": API_KEY},
        )

    if response.status_code != 200:
        raise HTTPException(status_code=response.status_code, detail=response.json())

    # Filter only positions with non-zero size
    positions = [p for p in response.json() if float(p.get("positionAmt", 0)) != 0]
    return positions
