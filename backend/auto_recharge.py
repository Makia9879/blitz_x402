#!/usr/bin/env python3
"""
自动完成 x402 充值流程的脚本

这个脚本会：
1. 调用充值接口获取 402 支付要求
2. 自动完成链上 MON 转账
3. 再次调用接口确认充值并更新余额

用法：
    python auto_recharge.py --amount 1.0 --user-address 0x...
    或
    python auto_recharge.py --amount 1.0  # 使用环境变量中的私钥地址
"""

import os
import sys
import argparse
import json
import time
from decimal import Decimal
from web3 import Web3
from eth_account import Account
from dotenv import load_dotenv
import httpx

# 加载环境变量
load_dotenv()

# 配置
RPC_URL = os.getenv("RPC_URL", "https://testnet-rpc.monad.xyz")
CHAIN_ID = int(os.getenv("CHAIN_ID", "10143"))
PRIVATE_KEY = os.getenv("PRIVATE_KEY", "")
TRANSIT_WALLET = os.getenv("TRANSIT_WALLET", "")
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")


def mon_to_wei(mon_amount: str) -> int:
    """将MON转换为wei（18位小数）"""
    return int(Decimal(mon_amount) * Decimal(10**18))


def wei_to_mon(wei_amount: int) -> str:
    """将wei转换为MON（18位小数）"""
    return str(Decimal(wei_amount) / Decimal(10**18))


def get_payment_requirement(amount: str, user_address: str = None) -> dict:
    """
    调用充值接口获取 402 支付要求
    
    Returns:
        dict: 支付要求信息，如果成功返回 payment_required=True
    """
    try:
        url = f"{BACKEND_URL}/api/v1/mcp/recharge"
        payload = {"amount": amount}
        if user_address:
            payload["user_address"] = user_address
        
        print(f"[Step 1] Requesting payment requirement from {url}...")
        print(f"[Step 1] Payload: {json.dumps(payload, indent=2)}")
        
        response = httpx.post(url, json=payload, timeout=30)
        
        if response.status_code == 402:
            data = response.json()
            print(f"[Step 1] ✅ Received 402 Payment Required")
            print(f"[Step 1] Payment details:")
            print(f"  - Amount: {data.get('amount')} MON ({data.get('amount_wei')} wei)")
            print(f"  - Pay to: {data.get('pay_to')}")
            print(f"  - Chain ID: {data.get('chain_id')}")
            print(f"  - Token: {data.get('token')}")
            return {
                "success": True,
                "payment_required": True,
                "data": data
            }
        else:
            return {
                "success": False,
                "error": f"Unexpected status code: {response.status_code}",
                "response": response.text
            }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


def send_mon_payment(
    to_address: str,
    amount_wei: int,
    private_key: str,
    wait_confirmation: bool = True,
) -> dict:
    """
    发送原生 MON 转账
    
    Returns:
        dict: {
            "success": bool,
            "tx_hash": str,
            "from": str,
            "to": str,
            "amount_wei": int,
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
        
        # 从私钥获取账户
        account = Account.from_key(private_key)
        sender_address = account.address
        
        # 转换地址格式
        to_address = Web3.to_checksum_address(to_address)
        
        # 检查余额
        balance_wei = w3.eth.get_balance(sender_address)
        balance_mon = wei_to_mon(balance_wei)
        
        print(f"[Step 2] Preparing payment...")
        print(f"  - From: {sender_address}")
        print(f"  - To: {to_address}")
        print(f"  - Amount: {wei_to_mon(amount_wei)} MON ({amount_wei} wei)")
        print(f"  - Balance: {balance_mon} MON ({balance_wei} wei)")
        
        # 估算 Gas
        estimated_gas = 21000
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
        
        # 签名交易
        signed_txn = account.sign_transaction(transaction)
        
        # 发送交易
        print(f"[Step 2] Sending transaction...")
        tx_hash = w3.eth.send_raw_transaction(signed_txn.rawTransaction)
        tx_hash_hex = tx_hash.hex()
        
        print(f"[Step 2] ✅ Transaction sent: {tx_hash_hex}")
        
        result = {
            "success": True,
            "tx_hash": tx_hash_hex,
            "from": sender_address,
            "to": to_address,
            "amount_wei": amount_wei,
        }
        
        # 等待确认
        if wait_confirmation:
            print(f"[Step 2] Waiting for confirmation...")
            receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
            
            if receipt.status == 1:
                print(f"[Step 2] ✅ Transaction confirmed in block {receipt.blockNumber}")
                result["block_number"] = receipt.blockNumber
                result["status"] = "confirmed"
            else:
                print(f"[Step 2] ❌ Transaction failed")
                result["status"] = "failed"
                result["success"] = False
                result["error"] = "Transaction reverted"
        else:
            result["status"] = "pending"
        
        return result
        
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


def confirm_recharge(user_address: str, amount: str, tx_hash: str) -> dict:
    """
    调用充值接口确认充值
    
    Returns:
        dict: 充值确认结果
    """
    try:
        url = f"{BACKEND_URL}/api/v1/mcp/recharge"
        payload = {
            "user_address": user_address,
            "amount": amount,
            "tx_hash": tx_hash
        }
        
        print(f"[Step 3] Confirming recharge...")
        print(f"[Step 3] Payload: {json.dumps(payload, indent=2)}")
        
        response = httpx.post(url, json=payload, timeout=30)
        
        if response.status_code == 200:
            data = response.json()
            print(f"[Step 3] ✅ Recharge confirmed successfully!")
            print(f"[Step 3] New balance: {data.get('new_balance')} wei ({wei_to_mon(int(data.get('new_balance', 0)))} MON)")
            return {
                "success": True,
                "data": data
            }
        else:
            return {
                "success": False,
                "error": f"Status code: {response.status_code}",
                "response": response.text
            }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


def main():
    parser = argparse.ArgumentParser(
        description="Automatically complete x402 recharge flow",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic usage (uses address from PRIVATE_KEY)
  python auto_recharge.py --amount 1.0
  
  # Specify user address
  python auto_recharge.py --amount 1.0 --user-address 0x...
  
  # Use custom private key
  python auto_recharge.py --amount 1.0 --private-key 0x...
        """
    )
    parser.add_argument(
        "--amount",
        type=str,
        required=True,
        help="Amount in MON (e.g., 1.0)"
    )
    parser.add_argument(
        "--user-address",
        type=str,
        help="User wallet address (optional, will use address from private key if not provided)"
    )
    parser.add_argument(
        "--private-key",
        type=str,
        help="Private key (optional, will use PRIVATE_KEY from .env)"
    )
    parser.add_argument(
        "--backend-url",
        type=str,
        default=BACKEND_URL,
        help=f"Backend API URL (default: {BACKEND_URL})"
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
    parser.add_argument(
        "--no-wait",
        action="store_true",
        help="Don't wait for transaction confirmation"
    )
    
    args = parser.parse_args()
    
    # 使用命令行参数覆盖环境变量
    global RPC_URL, CHAIN_ID, BACKEND_URL
    if args.rpc_url:
        RPC_URL = args.rpc_url
    if args.chain_id:
        CHAIN_ID = args.chain_id
    if args.backend_url:
        BACKEND_URL = args.backend_url
    
    # 获取私钥
    private_key = args.private_key or PRIVATE_KEY
    if not private_key:
        print("❌ Error: Private key not provided. Set PRIVATE_KEY in .env or pass --private-key")
        sys.exit(1)
    
    # 从私钥获取用户地址（如果没有提供）
    account = Account.from_key(private_key)
    user_address = args.user_address or account.address
    user_address = Web3.to_checksum_address(user_address)
    
    print("="*70)
    print("🚀 x402 Auto Recharge")
    print("="*70)
    print(f"Amount: {args.amount} MON")
    print(f"User Address: {user_address}")
    print(f"Backend URL: {BACKEND_URL}")
    print(f"RPC URL: {RPC_URL}")
    print(f"Chain ID: {CHAIN_ID}")
    print("="*70)
    print()
    
    # Step 1: 获取支付要求
    payment_req = get_payment_requirement(args.amount, user_address)
    if not payment_req["success"]:
        print(f"❌ Failed to get payment requirement: {payment_req.get('error')}")
        sys.exit(1)
    
    payment_data = payment_req["data"]
    pay_to = payment_data["pay_to"]
    amount_wei = int(payment_data["amount_wei"])
    
    print()
    
    # Step 2: 发送链上支付
    payment_result = send_mon_payment(
        to_address=pay_to,
        amount_wei=amount_wei,
        private_key=private_key,
        wait_confirmation=not args.no_wait,
    )
    
    if not payment_result["success"]:
        print(f"❌ Payment failed: {payment_result.get('error')}")
        sys.exit(1)
    
    tx_hash = payment_result["tx_hash"]
    print()
    
    # Step 3: 确认充值
    confirm_result = confirm_recharge(user_address, args.amount, tx_hash)
    
    if not confirm_result["success"]:
        print(f"❌ Recharge confirmation failed: {confirm_result.get('error')}")
        print(f"Response: {confirm_result.get('response')}")
        print(f"\nYou can manually confirm with:")
        print(f"curl -X POST {BACKEND_URL}/api/v1/mcp/recharge \\")
        print(f"  -H 'Content-Type: application/json' \\")
        print(f"  -d '{{")
        print(f'    "user_address": "{user_address}",')
        print(f'    "amount": "{args.amount}",')
        print(f'    "tx_hash": "{tx_hash}"')
        print(f"  }}'")
        sys.exit(1)
    
    # 成功！
    print()
    print("="*70)
    print("✅ Recharge Completed Successfully!")
    print("="*70)
    confirm_data = confirm_result["data"]
    print(f"Transaction Hash: {tx_hash}")
    print(f"New Balance: {confirm_data.get('new_balance')} wei ({wei_to_mon(int(confirm_data.get('new_balance', 0)))} MON)")
    print(f"Message: {confirm_data.get('message')}")
    print("="*70)
    
    sys.exit(0)


if __name__ == "__main__":
    main()

