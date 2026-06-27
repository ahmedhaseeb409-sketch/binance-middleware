from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel
from typing import Optional
import hmac
import hashlib
import time
import httpx
import os

app = FastAPI(title="Binance Spot Testnet Middleware")

# --- Config (set these as environment variables on Render) ---
API_KEY = os.environ.get("BINANCE_API_KEY", "YOUR_TESTNET_API_KEY")
API_SECRET = os.environ.get("BINANCE_API_SECRET", "YOUR_TESTNET_API_SECRET")
AGENT_TOKEN = os.environ.get("AGENT_TOKEN", "my-secret-agent-token")

BINANCE_TESTNET_URL = "https://testnet.binance.vision"  # Spot testnet
# ------------------------------------------------------------------ #

def sign(params: dict) -> str:
    """Create HMAC SHA256 signature required by Binance."""
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return hmac.new(API_SECRET.encode(), query.encode(), hashlib.sha256).hexdigest()

# ------------------------------------------------------------------ #
# Request models
# ------------------------------------------------------------------ #

class OrderRequest(BaseModel):
    symbol: str               # e.g. "BTCUSDT"
    side: str                 # "BUY" or "SELL"
    order_type: str           # "MARKET" or "LIMIT"
    quantity: float           # e.g. 0.001
    price: Optional[float] = None   # required for LIMIT orders

# ------------------------------------------------------------------ #
# Routes
# ------------------------------------------------------------------ #

@app.get("/")
def health():
    return {"status": "ok", "message": "Binance Spot Testnet Middleware is running"}


@app.post("/order")
async def place_order(order: OrderRequest, x_agent_token: str = Header(...)):
    """Place a spot order on Binance testnet."""

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

    # 3. Sign & send to Binance spot testnet
    params["signature"] = sign(params)

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{BINANCE_TESTNET_URL}/api/v3/order",   # Spot endpoint
            params=params,
            headers={"X-MBX-APIKEY": API_KEY},
        )

    if response.status_code != 200:
        raise HTTPException(status_code=response.status_code, detail=response.json())

    return response.json()


@app.get("/balance")
async def get_balance(x_agent_token: str = Header(...)):
    """Get spot testnet account balances (non-zero only)."""

    if x_agent_token != AGENT_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")

    params = {"timestamp": int(time.time() * 1000)}
    params["signature"] = sign(params)

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{BINANCE_TESTNET_URL}/api/v3/account",   # Spot account endpoint
            params=params,
            headers={"X-MBX-APIKEY": API_KEY},
        )

    if response.status_code != 200:
        raise HTTPException(status_code=response.status_code, detail=response.json())

    # Return only assets with a non-zero balance
    account = response.json()
    balances = [b for b in account["balances"] if float(b["free"]) > 0 or float(b["locked"]) > 0]
    return {"balances": balances}


@app.get("/orders")
async def get_open_orders(symbol: str, x_agent_token: str = Header(...)):
    """Get open orders for a symbol e.g. /orders?symbol=BTCUSDT"""

    if x_agent_token != AGENT_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")

    params = {
        "symbol": symbol.upper(),
        "timestamp": int(time.time() * 1000),
    }
    params["signature"] = sign(params)

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{BINANCE_TESTNET_URL}/api/v3/openOrders",
            params=params,
            headers={"X-MBX-APIKEY": API_KEY},
        )

    if response.status_code != 200:
        raise HTTPException(status_code=response.status_code, detail=response.json())

    return response.json()


@app.get("/price")
async def get_price(symbol: str):
    """Get current price for a symbol e.g. /price?symbol=BTCUSDT (no auth needed)"""

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{BINANCE_TESTNET_URL}/api/v3/ticker/price",
            params={"symbol": symbol.upper()},
        )

    if response.status_code != 200:
        raise HTTPException(status_code=response.status_code, detail=response.json())

    return response.json()
