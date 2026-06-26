from fastapi import FastAPI, HTTPException, Header, Request, BackgroundTasks
from pydantic import BaseModel
from typing import Optional
import hmac
import hashlib
import time
import httpx
import os

app = FastAPI(title="Binance Spot Testnet Middleware with Callbacks")

# --- Config (set these as environment variables on Render) ---
API_KEY = os.environ.get("BINANCE_API_KEY", "YOUR_TESTNET_API_KEY")
API_SECRET = os.environ.get("BINANCE_API_SECRET", "YOUR_TESTNET_API_SECRET")
AGENT_TOKEN = os.environ.get("AGENT_TOKEN", "my-secret-agent-token")

BINANCE_TESTNET_URL = "https://testnet.binance.vision"

def sign(params: dict) -> str:
    """Create HMAC SHA256 signature required by Binance."""
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return hmac.new(API_SECRET.encode(), query.encode(), hashlib.sha256).hexdigest()

async def send_callback(callback_url: Optional[str], data: dict):
    """Asynchronously posts data back into BuildMyAgent context."""
    if not callback_url:
        return
    async with httpx.AsyncClient() as client:
        try:
            await client.post(callback_url, json=data)
        except Exception as e:
            print(f"Callback failed: {e}")

# --- Helper to parse common body fields ---
async def parse_payload(request: Request):
    try:
        return await request.json()
    except:
        return {}

@app.get("/")
def health():
    return {"status": "ok", "message": "Binance Spot Testnet Middleware is running"}

@app.post("/balance")
async def get_balance(request: Request, background_tasks: BackgroundTasks, x_agent_token: str = Header(...)):
    if x_agent_token != AGENT_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")

    payload = await parse_payload(request)
    callback_url = payload.get("sendback_url")

    params = {"timestamp": int(time.time() * 1000)}
    params["signature"] = sign(params)

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{BINANCE_TESTNET_URL}/api/v3/account",
            params=params,
            headers={"X-MBX-APIKEY": API_KEY},
        )

    if response.status_code != 200:
        error_res = {"error": response.json()}
        background_tasks.add_task(send_callback, callback_url, error_res)
        return {"status": "error processed"}

    account = response.json()
    balances = [b for b in account["balances"] if float(b["free"]) > 0 or float(b["locked"]) > 0]
    
    # Format a direct asset dictionary for easier AI ingestion
    usdt_balance = next((b["free"] for b in account["balances"] if b["asset"] == "USDT"), "0.0")
    response_data = {"balances": balances, "usdt_balance": float(usdt_balance)}
    
    background_tasks.add_task(send_callback, callback_url, response_data)
    return {"status": "processing balance request"}

@app.post("/price")
async def get_price(request: Request, background_tasks: BackgroundTasks):
    payload = await parse_payload(request)
    callback_url = payload.get("sendback_url")
    symbol = payload.get("symbol", "BTCUSDT").upper()

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{BINANCE_TESTNET_URL}/api/v3/ticker/price",
            params={"symbol": symbol},
        )

    if response.status_code != 200:
        error_res = {"error": response.json()}
        background_tasks.add_task(send_callback, callback_url, error_res)
        return {"status": "error processed"}

    response_data = response.json()
    background_tasks.add_task(send_callback, callback_url, response_data)
    return {"status": "processing price request"}

@app.post("/order")
async def place_order(request: Request, background_tasks: BackgroundTasks, x_agent_token: str = Header(...)):
    if x_agent_token != AGENT_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")

    payload = await parse_payload(request)
    callback_url = payload.get("sendback_url")
    
    symbol = payload.get("symbol", "BTCUSDT").upper()
    side = payload.get("side", "BUY").upper()
    order_type = payload.get("order_type", "MARKET").upper()
    quantity = payload.get("quantity")
    price = payload.get("price")

    params = {
        "symbol": symbol,
        "side": side,
        "type": order_type,
        "quantity": quantity,
        "timestamp": int(time.time() * 1000),
    }

    if order_type == "LIMIT":
        if not price:
            raise HTTPException(status_code=400, detail="Price is required for LIMIT orders")
        params["price"] = price
        params["timeInForce"] = "GTC"

    params["signature"] = sign(params)

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{BINANCE_TESTNET_URL}/api/v3/order",
            params=params,
            headers={"X-MBX-APIKEY": API_KEY},
        )

    response_data = response.json()
    background_tasks.add_task(send_callback, callback_url, response_data)
    return {"status": "processing order placement"}
