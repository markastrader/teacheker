from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List
import aiohttp
import asyncio
import logging
from script import process_wallet, clear_cache

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI()

class WalletRequest(BaseModel):
    wallets: List[str]

@app.post("/check")
async def check_wallets(request: WalletRequest):
    logger.info("Starting wallet check for %s", request.wallets)
    try:
        clear_cache()
        invalid_wallets = [w for w in request.wallets if not w.startswith("0x") or len(w) != 42]
        if invalid_wallets:
            raise HTTPException(status_code=400, detail=f"Invalid wallet addresses: {invalid_wallets}")
        results = []
        async with aiohttp.ClientSession() as session:
            tasks = [process_wallet(wallet, session) for wallet in request.wallets]
            logger.info("Processing %d wallets", len(tasks))
            outputs = await asyncio.gather(*tasks, return_exceptions=True)
            for wallet, output in zip(request.wallets, outputs):
                if isinstance(output, Exception):
                    results.append({"wallet": wallet, "error": str(output)})
                else:
                    results.append({"wallet": wallet, "output": output})
        logger.info("Completed wallet check")
        return {"status": "success", "results": results}
    except Exception as e:
        logger.error("Error in check_wallets: %s", str(e))
        raise HTTPException(status_code=500, detail=str(e))
