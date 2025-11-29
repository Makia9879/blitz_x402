#!/usr/bin/env python3
"""
x402 Facilitator - 模仿 thirdweb 实现

功能：
1. 验证支付签名
2. 使用服务账户代付 Gas
3. 执行链上支付
4. 返回交易哈希
"""

import os
import json
import time
from typing import Optional, Dict, Any
from decimal import Decimal
from web3 import Web3
from eth_account import Account
from eth_account.messages import encode_defunct
from dotenv import load_dotenv

load_dotenv()

# 配置
RPC_URL = os.getenv("RPC_URL", "https://testnet-rpc.monad.xyz")
CHAIN_ID = int(os.getenv("CHAIN_ID", "10143"))
FACILITATOR_PRIVATE_KEY = os.getenv("PRIVATE_KEY", "")  # Facilitator 服务账户私钥
FACILITATOR_ADDRESS = None  # 从私钥推导

if FACILITATOR_PRIVATE_KEY:
    FACILITATOR_ADDRESS = Account.from_key(FACILITATOR_PRIVATE_KEY).address

# 初始化 Web3
w3 = Web3(Web3.HTTPProvider(RPC_URL))


def mon_to_wei(mon_amount: str) -> int:
    """将MON转换为wei（18位小数）"""
    return int(Decimal(mon_amount) * Decimal(10**18))


def wei_to_mon(wei_amount: int) -> str:
    """将wei转换为MON（18位小数）"""
    return str(Decimal(wei_amount) / Decimal(10**18))


def create_payment_message(
    user_address: str,
    pay_to: str,
    amount_wei: int,
    chain_id: int,
    nonce: Optional[str] = None,
) -> str:
    """
    创建支付消息（用于签名）
    
    格式类似 EIP-712，但简化版本
    """
    if nonce is None:
        nonce = str(int(time.time() * 1000))  # 使用时间戳作为 nonce
    
    message = {
        "types": {
            "EIP712Domain": [
                {"name": "name", "type": "string"},
                {"name": "version", "type": "string"},
                {"name": "chainId", "type": "uint256"},
            ],
            "Payment": [
                {"name": "user", "type": "address"},
                {"name": "payTo", "type": "address"},
                {"name": "amount", "type": "uint256"},
                {"name": "nonce", "type": "string"},
            ],
        },
        "primaryType": "Payment",
        "domain": {
            "name": "x402 Payment",
            "version": "1",
            "chainId": chain_id,
        },
        "message": {
            "user": user_address,
            "payTo": pay_to,
            "amount": amount_wei,
            "nonce": nonce,
        },
    }
    
    return json.dumps(message, sort_keys=True)


def verify_payment_signature(
    user_address: str,
    pay_to: str,
    amount_wei: int,
    signature: str,
    chain_id: int,
) -> bool:
    """
    验证支付签名
    
    Args:
        user_address: 用户地址
        pay_to: 收款地址
        amount_wei: 金额（wei）
        signature: 签名（hex string，0x开头）
        chain_id: 链 ID
    
    Returns:
        bool: 签名是否有效
    """
    try:
        # 创建支付消息（简化版本，使用简单的字符串消息）
        # 实际应用中可以使用 EIP-712 结构化签名
        message_text = f"x402 Payment\nUser: {user_address}\nPayTo: {pay_to}\nAmount: {amount_wei}\nChain: {chain_id}"
        
        # 编码消息
        message_hash = encode_defunct(text=message_text)
        
        # 恢复签名者地址
        recovered_address = Account.recover_message(message_hash, signature=signature)
        
        # 验证地址是否匹配
        is_valid = recovered_address.lower() == user_address.lower()
        if is_valid:
            print(f"[Facilitator] Payment signature verified for user: {user_address}")
        else:
            print(f"[Facilitator] Signature mismatch: expected {user_address}, got {recovered_address}")
        return is_valid
    except Exception as e:
        print(f"[Facilitator] Signature verification failed: {e}")
        return False


# 用于存储已处理的 payment_id（防止重放攻击）
_processed_payment_ids = set()


def settle_payment(
    user_address: str,
    pay_to: str,
    amount_wei: int,
    payment_signature: str,
    payment_id: Optional[str] = None,
    chain_id: Optional[int] = None,
) -> Dict[str, Any]:
    """
    结算支付（Facilitator 核心功能）
    
    流程：
    1. 检查 payment_id 是否已处理（防重放）
    2. 验证支付签名
    3. 使用 Facilitator 账户代付 Gas 并执行支付
    4. 等待交易确认
    5. 记录 payment_id（如果提供）
    6. 返回交易哈希
    
    Args:
        user_address: 用户地址
        pay_to: 收款地址（TRANSIT_WALLET）
        amount_wei: 支付金额（wei）
        payment_signature: 支付签名
        payment_id: 支付请求唯一标识符（可选，用于防重放）
        chain_id: 链 ID（可选，默认使用配置的）
    
    Returns:
        dict: {
            "success": bool,
            "tx_hash": str,
            "error": str (如果失败)
        }
    """
    if not FACILITATOR_PRIVATE_KEY:
        return {
            "success": False,
            "error": "Facilitator private key not configured"
        }
    
    if chain_id is None:
        chain_id = CHAIN_ID
    
    try:
        # 1. 检查 payment_id 是否已处理（防重放攻击）
        if payment_id:
            if payment_id in _processed_payment_ids:
                return {
                    "success": False,
                    "error": f"Payment ID {payment_id} has already been processed (replay attack prevented)"
                }
            print(f"[Facilitator] Payment ID: {payment_id}")
        
        # 2. 验证支付签名
        print(f"[Facilitator] Verifying payment signature...")
        if not verify_payment_signature(user_address, pay_to, amount_wei, payment_signature, chain_id):
            return {
                "success": False,
                "error": "Invalid payment signature"
            }
        
        print(f"[Facilitator] Payment signature verified for user: {user_address}")
        
        # 3. 记录 payment_id（在验证签名成功后）
        if payment_id:
            _processed_payment_ids.add(payment_id)
            print(f"[Facilitator] Payment ID recorded: {payment_id}")
        
        # 2. 检查 Facilitator 账户余额
        facilitator_account = Account.from_key(FACILITATOR_PRIVATE_KEY)
        facilitator_address = facilitator_account.address
        
        balance_wei = w3.eth.get_balance(facilitator_address)
        estimated_gas = 21000
        gas_price = w3.eth.gas_price
        total_cost = amount_wei + (estimated_gas * gas_price)
        
        print(f"[Facilitator] Facilitator balance: {wei_to_mon(balance_wei)} MON")
        print(f"[Facilitator] Payment amount: {wei_to_mon(amount_wei)} MON")
        print(f"[Facilitator] Estimated gas cost: {wei_to_mon(estimated_gas * gas_price)} MON")
        
        if balance_wei < total_cost:
            return {
                "success": False,
                "error": f"Insufficient facilitator balance. Need {wei_to_mon(total_cost)} MON, but have {wei_to_mon(balance_wei)} MON"
            }
        
        # 5. 构建并发送交易（从 Facilitator 账户支付到 pay_to）
        nonce = w3.eth.get_transaction_count(facilitator_address)
        
        transaction = {
            "to": Web3.to_checksum_address(pay_to),
            "value": amount_wei,
            "gas": estimated_gas,
            "gasPrice": gas_price,
            "nonce": nonce,
            "chainId": chain_id,
        }
        
        # 签名交易
        signed_txn = facilitator_account.sign_transaction(transaction)
        
        # 发送交易
        print(f"[Facilitator] Sending payment transaction...")
        tx_hash = w3.eth.send_raw_transaction(signed_txn.rawTransaction)
        tx_hash_hex = tx_hash.hex()
        
        print(f"[Facilitator] Transaction sent: {tx_hash_hex}")
        
        # 6. 等待确认
        print(f"[Facilitator] Waiting for confirmation...")
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        
        if receipt.status == 1:
            print(f"[Facilitator] ✅ Payment settled successfully in block {receipt.blockNumber}")
            return {
                "success": True,
                "tx_hash": tx_hash_hex,
                "block_number": receipt.blockNumber,
                "from": facilitator_address,
                "to": pay_to,
                "amount_wei": amount_wei,
            }
        else:
            return {
                "success": False,
                "error": "Transaction reverted"
            }
            
    except Exception as e:
        print(f"[Facilitator] Error settling payment: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def create_payment_requirement(
    amount: str,
    pay_to: str,
    user_address: str,
    chain_id: Optional[int] = None,
) -> Dict[str, Any]:
    """
    创建支付要求（用于返回 402 响应）
    
    Returns:
        dict: 支付要求信息
    """
    if chain_id is None:
        chain_id = CHAIN_ID
    
    amount_wei = mon_to_wei(amount)
    
    return {
        "payment_required": True,
        "amount": amount,
        "amount_wei": str(amount_wei),
        "chain_id": chain_id,
        "token": "MON",
        "pay_to": Web3.to_checksum_address(pay_to),
        "user_address": Web3.to_checksum_address(user_address),
        "description": "Please sign payment message and provide signature",
        "instructions": "Sign the payment message with your wallet and provide the signature in payment_signature field. The facilitator will pay on your behalf (no gas needed).",
        "facilitator_available": FACILITATOR_PRIVATE_KEY is not None,
    }


if __name__ == "__main__":
    # 测试代码
    print("x402 Facilitator Test")
    print("=" * 60)
    
    if not FACILITATOR_PRIVATE_KEY:
        print("❌ Error: FACILITATOR_PRIVATE_KEY not configured")
        exit(1)
    
    facilitator_account = Account.from_key(FACILITATOR_PRIVATE_KEY)
    print(f"Facilitator Address: {facilitator_account.address}")
    print(f"Chain ID: {CHAIN_ID}")
    print(f"RPC URL: {RPC_URL}")
    print("=" * 60)

