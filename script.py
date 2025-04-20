import logging
import aiohttp
from web3 import Web3
import requests
import json
import os
from datetime import datetime, timezone, timedelta
import logging
import aiohttp
import asyncio
import random
from tabulate import tabulate
import gzip

# Konfigurasi logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler()  # Log ke stdout, ditangkap oleh Vercel
    ]
)
logger = logging.getLogger(__name__)

# Konfigurasi
CONFIG = {
    "BLOCKSCOUT_API": "https://sepolia.tea.xyz/api",
    "OPENCHAIN_API": "https://api.openchain.xyz/signature-database/v1/lookup",
    "RPC_URL": "https://tea-sepolia.g.alchemy.com/v2/{}",
    "CACHE_FILE": "transactions_cache.json.gz",
    "FAUCET_ADDRESS": "0xD991A4bb721f2E9A5E62449FA617274901e6ADDe",
    "PAGE_SIZE": 1000,
    "CACHE_TTL_MINUTES": 60,
    "API_KEYS": [
        os.getenv("ALCHEMY_API_KEY_1", "qgL6v56zfbr--COQOAxgCugruEzQjQJ4"),
        os.getenv("ALCHEMY_API_KEY_2", "5bZaMAXCn4VyZ9lIB32STcZYpFYIg4k7"),
        os.getenv("ALCHEMY_API_KEY_3", "d_E1VMblNAWtHlntQ5w0grtEwdTddGNw"),
        os.getenv("ALCHEMY_API_KEY_4", "yHWN4zeqgZUw8uu4pXZcvwDAHYgtSoHD"),
        os.getenv("ALCHEMY_API_KEY_5", "O_SNUc92TunD0mLAIqNrR40SsvXmXFX1"),
        os.getenv("ALCHEMY_API_KEY_6", "ycrzi-3ijLmvGFeqAT5XvHrtdCZ97SgG"),
        os.getenv("ALCHEMY_API_KEY_7", "02GajyA6B9LvVkCp2tCrs5CKMSVtGhOZ"),
        os.getenv("ALCHEMY_API_KEY_8", "Uja9gLPYaPA8GkW-voer_vCt-0IpC6GA"),
        os.getenv("ALCHEMY_API_KEY_9", "PVVFo13r7f7ePD59saCs_jtrHBftyQGO"),
        os.getenv("ALCHEMY_API_KEY_10", "wcFrYLMUYpb_QjtbinAI8ybuknRIGvlK"),
    ],
    "METHODS": {
        "Claim Faucet": None,
        "Staked": "0xa694fc3a",
        "Unstaked": "0x2e17de78",
        "Claim Reward": "0x3d18b912",
        "Swapped": "0x7ff36ab5",
        "Transfer": None,
        "Mint NFT": "0xd85d3d27",
        "Deploy": None,
        "Add LP": "0xf305d719",
        "Deposit": "0xd0e30db0",
        "Withdraw": "0x2e1a7d4d",
        "Remove Liquidity": ["0x5b0d5984", "0x02751cec", "0x2195995c", "0xded9382a"],
        "Custom Transfer": "0x2e1a7d4d",
    }
}

if not any(CONFIG["API_KEYS"]):
    raise ValueError("Setidaknya satu API key harus disetel di variabel lingkungan.")

# Inisialisasi Web3 dengan rotasi API key sederhana
def get_web3():
    for api_key in random.sample(CONFIG["API_KEYS"], len(CONFIG["API_KEYS"])):
        w3 = Web3(Web3.HTTPProvider(CONFIG["RPC_URL"].format(api_key)))
        if w3.is_connected():
            logger.info(f"Terhubung dengan API key {api_key[:6]}...")
            return w3, api_key
        logger.error(f"API key {api_key[:6]}... gagal, mencoba key berikutnya.")
    raise ConnectionError("Tidak ada API key yang dapat terhubung.")

w3, CURRENT_API_KEY = get_web3()

# Fungsi untuk mencari signature di OpenChain
async def lookup_signature(session, signature):
    params = {"function": signature}
    try:
        async with session.get(CONFIG["OPENCHAIN_API"], params=params, timeout=5) as response:
            if response.status == 200:
                data = await response.json()
                results = data.get("result", {}).get("function", {}).get(signature, [])
                if results:
                    return [r["name"] for r in results]
                return [f"Unknown ({signature})"]
            return [f"Unknown ({signature})"]
    except Exception as e:
        logger.error(f"Error mencari signature {signature}: {e}")
        return [f"Unknown ({signature})"]

# Fungsi untuk memuat/menyimpan cache dengan kompresi
def load_cache(wallet_address):
    try:
        with gzip.open(CONFIG["CACHE_FILE"], "rt", encoding="utf-8") as f:
            cache = json.load(f)
        cached_data = cache.get(wallet_address, {})
        cached_time = cached_data.get("timestamp", "1970-01-01T00:00:00+00:00")
        cached_dt = datetime.fromisoformat(cached_time.replace("Z", "+00:00"))
        if datetime.now(timezone.utc) - cached_dt < timedelta(minutes=CONFIG["CACHE_TTL_MINUTES"]):
            return cached_data
        logger.info(f"Cache untuk {wallet_address} kadaluarsa, akan mengambil data baru.")
        return {}
    except FileNotFoundError:
        return {}

def save_cache(wallet_address, data):
    cache = {}
    try:
        with gzip.open(CONFIG["CACHE_FILE"], "rt", encoding="utf-8") as f:
            cache = json.load(f)
    except FileNotFoundError:
        pass
    cache[wallet_address] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "transactions": data["transactions"],
        "token_transactions": data["token_transactions"]
    }
    with gzip.open(CONFIG["CACHE_FILE"], "wt", encoding="utf-8") as f:
        json.dump(cache, f, indent=2)

# Fungsi untuk menghapus cache
def clear_cache():
    try:
        if os.path.exists(CONFIG["CACHE_FILE"]):
            os.remove(CONFIG["CACHE_FILE"])
            logger.info(f"File cache {CONFIG['CACHE_FILE']} dihapus.")
    except Exception as e:
        logger.error(f"Error menghapus cache: {e}")

# Fungsi untuk mendapatkan transaksi dari Blockscout secara async
async def get_transactions_blockscout_async(session, wallet_address):
    transactions = []
    page = 1
    while True:
        params = {
            "module": "account",
            "action": "txlist",
            "address": wallet_address,
            "startblock": 0,
            "endblock": "latest",
            "sort": "asc",
            "page": page,
            "offset": CONFIG["PAGE_SIZE"]
        }
        try:
            async with session.get(CONFIG["BLOCKSCOUT_API"], params=params, timeout=20) as response:
                if response.status == 200:
                    data = await response.json()
                    if data["status"] == "1":
                        page_transactions = data["result"]
                        transactions.extend(page_transactions)
                        if len(page_transactions) < CONFIG["PAGE_SIZE"]:
                            break
                        page += 1
                    elif data["status"] == "0" and "No transactions found" in data.get("message", ""):
                        logger.info(f"Tidak ada transaksi ditemukan di Blockscout untuk {wallet_address}")
                        break
                    else:
                        logger.error(f"Error fetching transactions for {wallet_address}: {data.get('message', 'Unknown error')}")
                        break
                elif response.status == 429:
                    logger.warning(f"Rate limit untuk Blockscout, menunggu...")
                    await asyncio.sleep(5)
                else:
                    logger.error(f"Error fetching transactions for {wallet_address}: HTTP {response.status}")
                    break
        except Exception as e:
            logger.error(f"Exception fetching transactions for {wallet_address}: {e}")
            break
    logger.warning(f"Total {len(transactions)} transaksi diambil dari Blockscout untuk {wallet_address}")
    return transactions

# Fungsi untuk mendapatkan transaksi token dari Blockscout secara async
async def get_token_transactions_blockscout_async(session, wallet_address):
    token_transactions = []
    page = 1
    while True:
        params = {
            "module": "account",
            "action": "tokentx",
            "address": wallet_address,
            "startblock": 0,
            "endblock": "latest",
            "sort": "asc",
            "page": page,
            "offset": CONFIG["PAGE_SIZE"]
        }
        try:
            async with session.get(CONFIG["BLOCKSCOUT_API"], params=params, timeout=20) as response:
                if response.status == 200:
                    data = await response.json()
                    if data["status"] == "1":
                        page_transactions = data["result"]
                        token_transactions.extend(page_transactions)
                        if len(page_transactions) < CONFIG["PAGE_SIZE"]:
                            break
                        page += 1
                    elif data["status"] == "0" and "No token transfers found" in data.get("message", ""):
                        logger.info(f"Tidak ada transaksi token ditemukan di Blockscout untuk {wallet_address}")
                        break
                    else:
                        logger.error(f"Error fetching token transactions for {wallet_address}: {data.get('message', 'Unknown error')}")
                        break
                elif response.status == 429:
                    logger.warning(f"Rate limit untuk Blockscout, menunggu...")
                    await asyncio.sleep(5)
                else:
                    logger.error(f"Error fetching token transactions for {wallet_address}: HTTP {response.status}")
                    break
        except Exception as e:
            logger.error(f"Exception fetching token transactions for {wallet_address}: {e}")
            break
    logger.warning(f"Total {len(token_transactions)} transaksi token diambil dari Blockscout untuk {wallet_address}")
    return token_transactions

# Fungsi untuk memeriksa metode dan mengidentifikasi semua fungsi
async def check_methods(transactions, token_transactions, wallet_address):
    method_status = {method: False for method in CONFIG["METHODS"]}
    method_details = {method: [] for method in CONFIG["METHODS"]}
    all_functions = set()
    
    # Mengumpulkan semua signature unik dari transaksi
    signatures = set()
    for tx in transactions:
        input_data = tx.get("input", "0x")
        if input_data != "0x" and len(input_data) >= 10:
            signatures.add(input_data[:10])
    
    # Mencari nama fungsi dari signature
    async with aiohttp.ClientSession() as session:
        tasks = [lookup_signature(session, sig) for sig in signatures]
        results = await asyncio.gather(*tasks)
        for sig, names in zip(signatures, results):
            for name in names:
                all_functions.add(f"{name} ({sig})")
    
    # Periksa transaksi
    for tx in transactions:
        tx_hash = tx.get("hash", "unknown")
        if float(tx["value"]) > 0:
            value_in_eth = w3.from_wei(int(tx["value"]), "ether")
            if value_in_eth == 50 and tx["to"].lower() == wallet_address.lower():
                method_status["Claim Faucet"] = True
                method_details["Claim Faucet"].append(f"Tx: {tx_hash}, From: {tx['from']}, Value: 50 ETH")
            method_status["Transfer"] = True
            method_details["Transfer"].append(f"Tx: {tx_hash}, Value: {value_in_eth} ETH")
        if tx["from"].lower() == CONFIG["FAUCET_ADDRESS"].lower() and float(tx["value"]) == 50:
            method_status["Claim Faucet"] = True
            method_details["Claim Faucet"].append(f"Tx: {tx_hash}, From: {tx['from']}, Value: 50 ETH")
        if tx["to"] == "" and tx.get("contractAddress"):
            method_status["Deploy"] = True
            method_details["Deploy"].append(f"Tx: {tx_hash}, Contract: {tx['contractAddress']}")
        input_data = tx.get("input", "0x")
        if input_data != "0x" and len(input_data) >= 10:
            function_signature = input_data[:10]
            logger.debug(f"Transaksi {tx_hash}: Signature {function_signature}, Contract: {tx.get('to', 'unknown')}")
            for method, signature in CONFIG["METHODS"].items():
                signatures_to_check = signature if isinstance(signature, list) else [signature]
                if function_signature in signatures_to_check and signature is not None:
                    method_status[method] = True
                    method_details[method].append(f"Tx: {tx_hash}, Contract: {tx.get('to', 'unknown')}")
                    logger.info(f"{method} terdeteksi untuk {wallet_address}: Tx {tx_hash}, Signature {function_signature}")
                elif function_signature in signatures_to_check:
                    logger.warning(f"Transaksi {tx_hash} memiliki signature {function_signature} tetapi tidak ditandai untuk {method}")
    
    # Periksa transaksi token
    for tx in token_transactions:
        tx_hash = tx.get("hash", "unknown")
        if "tokenStandard" in tx and tx["tokenStandard"] == "ERC-721":
            method_status["Mint NFT"] = True
            method_details["Mint NFT"].append(f"Tx: {tx_hash}, Token: {tx.get('tokenName')}")
        if "tokenStandard" in tx and tx["tokenStandard"] == "ERC-20":
            value = float(tx.get("value", 0)) / (10 ** int(tx.get("tokenDecimal", 18)))
            if value == 50 and tx["to"].lower() == wallet_address.lower():
                method_status["Claim Faucet"] = True
                method_details["Claim Faucet"].append(f"Tx: {tx_hash}, From: {tx['from']}, Value: 50 {tx.get('tokenSymbol', 'Token')}")
            method_status["Transfer"] = True
            method_details["Transfer"].append(f"Tx: {tx_hash}, Token: {tx.get('tokenName')}")

    return method_status, method_details, all_functions

# Fungsi untuk menampilkan hasil
def display_results(wallet_address, method_status, method_details, all_functions):
    print(f"\n{'='*50}")
    print(f"Laporan Analisis Dompet: {wallet_address}")
    print(f"{'='*50}\n")
    
    table_data = []
    for method, status in method_status.items():
        details = "; ".join(method_details[method])[:100] or "Tidak ada transaksi"
        if len(details) > 100:
            details = details[:97] + "..."
        table_data.append([method, "✅" if status else "⬜", details])
    
    print("Metode yang Ditetapkan:")
    print(tabulate(
        table_data,
        headers=["Metode", "Status", "Detail Transaksi"],
        tablefmt="grid",
        stralign="left"
    ))
    
    print("\nSemua Fungsi yang Terdeteksi:")
    for func in sorted(all_functions):
        print(f"✅ {func}")
    
    print(f"\n{'-'*50}")
    print("Panduan Verifikasi:")
    print(f"- Claim Faucet: Periksa https://sepolia.tea.xyz/address/{CONFIG['FAUCET_ADDRESS']}")
    print("- Remove Liquidity: Periksa transaksi dengan signature 0x5b0d5984, 0x02751cec, 0x2195995c, atau 0xded9382a di https://sepolia.tea.xyz/")
    print("- Staked/Unstaked: Gunakan hash transaksi di https://sepolia.tea.xyz/")
    print("- Lainnya: Hubungi tim Tea di https://tea.xyz untuk kontrak atau signature tambahan")
    print(f"{'-'*50}")

# Fungsi untuk memproses satu dompet
async def process_wallet(wallet, session):
    print(f"\nMemeriksa dompet: {wallet}")
    print("Sabar dan tunggu sambil ngopi, checker sedang berlangsung...")
    logger.warning(f"Memulai pemeriksaan untuk dompet: {wallet}")

    # Cek cache
    cached_data = load_cache(wallet)
    if cached_data:
        transactions = cached_data.get("transactions", [])
        token_transactions = cached_data.get("token_transactions", [])
        logger.info(f"Menggunakan data dari cache untuk {wallet}")
    else:
        # Ambil data dari Blockscout
        async with aiohttp.ClientSession() as blockscout_session:
            blockscout_tasks = [
                get_transactions_blockscout_async(blockscout_session, wallet),
                get_token_transactions_blockscout_async(blockscout_session, wallet)
            ]
            transactions, token_transactions = await asyncio.gather(*blockscout_tasks)

        if not transactions and not token_transactions:
            logger.error(f"Tidak ada transaksi ditemukan untuk {wallet}. Mungkin dompet belum digunakan.")
            method_status = {method: False for method in CONFIG["METHODS"]}
            method_details = {method: [] for method in CONFIG["METHODS"]}
            all_functions = set()
            display_results(wallet, method_status, method_details, all_functions)
            print(f"Tidak ada transaksi ditemukan untuk {wallet}. Periksa status dompet di https://sepolia.tea.xyz/address/{wallet}")
            return

        save_cache(wallet, {
            "transactions": transactions,
            "token_transactions": token_transactions
        })
        logger.warning(f"Data disimpan ke cache untuk {wallet}")

    method_status, method_details, all_functions = await check_methods(transactions, token_transactions, wallet)
    display_results(wallet, method_status, method_details, all_functions)

# Main program
async def main():
    clear_cache()
    print("Masukkan alamat dompet (pisahkan dengan koma, atau ketik 'ok' untuk mengakhiri):")
    wallets = []
    while True:
        input_str = input("> ")
        if input_str.strip().lower() == "ok":
            break
        wallets.extend([addr.strip() for addr in input_str.split(",") if w3.is_address(addr.strip())])
    
    if not wallets:
        print("Tidak ada dompet valid yang dimasukkan.")
        return
    
    async with aiohttp.ClientSession() as session:
        for wallet in wallets:
            await process_wallet(wallet, session)

if __name__ == "__main__":
    asyncio.run(main())
