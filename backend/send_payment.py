#!/usr/bin/env python3
"""
链上支付脚本 - 自动完成 x402 支付流程

用法：
    python send_payment.py --amount 1.0 --to 0x... --from 0x...
    或
    python send_payment.py --amount 1.0 --to 0x...  # 使用环境变量中的私钥
"""

import os
import sys
import argparse
from decimal import Decimal
from web3 import Web3
from eth_account import Account
from dotenv import load_dotenv
import time

# 加载环境变量
load_dotenv()

# 配置
RPC_URL = os.getenv("RPC_URL", "https://testnet-rpc.monad.xyz")
CHAIN_ID = int(os.getenv("CHAIN_ID", "10143"))
PRIVATE_KEY = os.getenv("PRIVATE_KEY", "")
TRANSIT_WALLET = os.getenv("TRANSIT_WALLET", "")


def mon_to_wei(mon_amount: str) -> int:
    """将MON转换为wei（18位小数）"""
    return int(Decimal(mon_amount) * Decimal(10**18))


def wei_to_mon(wei_amount: int) -> str:
    """将wei转换为MON（18位小数）"""
    return str(Decimal(wei_amount) / Decimal(10**18))


def send_mon_payment(
    from_address: str,
    to_address: str,
    amount_mon: str,
    private_key: str = None,
    wait_confirmation: bool = True,
) -> dict:
    """
    发送原生 MON 转账
    
    Args:
        from_address: 发送方地址（可选，如果不提供则从私钥推导）
        to_address: 接收方地址（中转站钱包）
        amount_mon: 金额（MON，如 "1.0"）
        private_key: 私钥（如果不提供则从环境变量读取）
        wait_confirmation: 是否等待交易确认
    
    Returns:
        dict: {
            "success": bool,
            "tx_hash": str,
            "from": str,
            "to": str,
            "amount_wei": int,
            "amount_mon": str,
            "block_number": int (如果已确认)
        }
    """
    try:
        # 初始化 Web3
        w3 = Web3(Web3.HTTPProvider(RPC_URL))
        
        if not w3.is_connected():
            return {
                "success": False,
                "error": f"Failed to connect to RPC: {RPC_URL}"
            }
        
        # 获取私钥
        if not private_key:
            private_key = PRIVATE_KEY
        
        if not private_key:
            return {
                "success": False,
                "error": "Private key not provided. Set PRIVATE_KEY in .env or pass --private-key"
            }
        
        # 从私钥获取账户
        account = Account.from_key(private_key)
        sender_address = account.address
        
        # 如果提供了 from_address，验证是否匹配
        if from_address:
            from_address = Web3.to_checksum_address(from_address)
            if from_address.lower() != sender_address.lower():
                return {
                    "success": False,
                    "error": f"Private key address ({sender_address}) doesn't match from_address ({from_address})"
                }
        
        # 转换地址格式
        to_address = Web3.to_checksum_address(to_address)
        
        # 转换金额
        amount_wei = mon_to_wei(amount_mon)
        
        if amount_wei <= 0:
            return {
                "success": False,
                "error": f"Invalid amount: {amount_mon} MON"
            }
        
        # 检查余额
        balance_wei = w3.eth.get_balance(sender_address)
        balance_mon = wei_to_mon(balance_wei)
        
        print(f"[Payment] Sender: {sender_address}")
        print(f"[Payment] Receiver: {to_address}")
        print(f"[Payment] Amount: {amount_mon} MON ({amount_wei} wei)")
        print(f"[Payment] Balance: {balance_mon} MON ({balance_wei} wei)")
        
        # 估算 Gas（需要一些余额用于 Gas 费）
        estimated_gas = 21000  # 标准转账的 Gas
        gas_price = w3.eth.gas_price
        
        total_cost = amount_wei + (estimated_gas * gas_price)
        
        if balance_wei < total_cost:
            return {
                "success": False,
                "error": f"Insufficient balance. Need {wei_to_mon(total_cost)} MON (including gas), but have {balance_mon} MON"
            }
        
        # 获取 nonce
        nonce = w3.eth.get_transaction_count(sender_address)
        
        # 构建交易
        transaction = {
            "to": to_address,
            "value": amount_wei,
            "gas": estimated_gas,
            "gasPrice": gas_price,
            "nonce": nonce,
            "chainId": CHAIN_ID,
        }
        
        print(f"[Payment] Building transaction: nonce={nonce}, gas={estimated_gas}, gasPrice={gas_price}")
        
        # 签名交易
        signed_txn = account.sign_transaction(transaction)
        
        # 发送交易
        print(f"[Payment] Sending transaction...")
        tx_hash = w3.eth.send_raw_transaction(signed_txn.rawTransaction)
        tx_hash_hex = tx_hash.hex()
        
        print(f"[Payment] Transaction sent: {tx_hash_hex}")
        
        result = {
            "success": True,
            "tx_hash": tx_hash_hex,
            "from": sender_address,
            "to": to_address,
            "amount_wei": amount_wei,
            "amount_mon": amount_mon,
        }
        
        # 等待确认
        if wait_confirmation:
            print(f"[Payment] Waiting for confirmation...")
            receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
            
            if receipt.status == 1:
                print(f"[Payment] ✅ Transaction confirmed in block {receipt.blockNumber}")
                result["block_number"] = receipt.blockNumber
                result["status"] = "confirmed"
            else:
                print(f"[Payment] ❌ Transaction failed")
                result["status"] = "failed"
                result["success"] = False
                result["error"] = "Transaction reverted"
        else:
            result["status"] = "pending"
            print(f"[Payment] Transaction pending. Check status with tx_hash: {tx_hash_hex}")
        
        return result
        
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


def main():
    parser = argparse.ArgumentParser(description="Send MON payment via x402")
    parser.add_argument(
        "--amount",
        type=str,
        required=True,
        help="Amount in MON (e.g., 1.0)"
    )
    parser.add_argument(
        "--to",
        type=str,
        required=True,
        help="Recipient address (transit wallet)"
    )
    parser.add_argument(
        "--from",
        type=str,
        dest="from_addr",
        help="Sender address (optional, will use address from private key)"
    )
    parser.add_argument(
        "--private-key",
        type=str,
        help="Private key (optional, will use PRIVATE_KEY from .env)"
    )
    parser.add_argument(
        "--no-wait",
        action="store_true",
        help="Don't wait for transaction confirmation"
    )
    parser.add_argument(
        "--rpc-url",
        type=str,
        help=f"RPC URL (default: {RPC_URL})"
    )
    parser.add_argument(
        "--chain-id",
        type=int,
        help=f"Chain ID (default: {CHAIN_ID})"
    )
    
    args = parser.parse_args()
    
    # 使用命令行参数覆盖环境变量
    global RPC_URL, CHAIN_ID
    if args.rpc_url:
        RPC_URL = args.rpc_url
    if args.chain_id:
        CHAIN_ID = args.chain_id
    
    # 如果没有提供 to 地址，使用环境变量中的 TRANSIT_WALLET
    to_address = args.to or TRANSIT_WALLET
    if not to_address:
        print("Error: --to address is required or set TRANSIT_WALLET in .env")
        sys.exit(1)
    
    # 发送支付
    result = send_mon_payment(
        from_address=args.from_addr or "",
        to_address=to_address,
        amount_mon=args.amount,
        private_key=args.private_key,
        wait_confirmation=not args.no_wait,
    )
    
    # 输出结果
    if result["success"]:
        print("\n" + "="*60)
        print("✅ Payment Successful!")
        print("="*60)
        print(f"Transaction Hash: {result['tx_hash']}")
        print(f"From: {result['from']}")
        print(f"To: {result['to']}")
        print(f"Amount: {result['amount_mon']} MON ({result['amount_wei']} wei)")
        if "block_number" in result:
            print(f"Block Number: {result['block_number']}")
        print("="*60)
        
        # 输出用于后续调用的 JSON
        print("\nUse this tx_hash to confirm recharge:")
        print(f"curl -X POST http://localhost:8000/api/v1/mcp/recharge \\")
        print(f"  -H 'Content-Type: application/json' \\")
        print(f"  -d '{{")
        print(f'    "user_address": "{result["from"]}",')
        print(f'    "amount": "{result["amount_mon"]}",')
        print(f'    "tx_hash": "{result["tx_hash"]}"')
        print(f"  }}'")
        
        sys.exit(0)
    else:
        print("\n" + "="*60)
        print("❌ Payment Failed!")
        print("="*60)
        print(f"Error: {result.get('error', 'Unknown error')}")
        print("="*60)
        sys.exit(1)


if __name__ == "__main__":
    main()

