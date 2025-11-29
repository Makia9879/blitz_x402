#!/usr/bin/env python3
"""
x402 Facilitator 客户端示例

展示如何使用 x402 facilitator 进行充值：
1. 调用 API 获取 402 支付要求
2. 使用钱包签名支付消息
3. 将签名发送给 API，facilitator 自动代付
"""

import json
import httpx
from web3 import Web3
from eth_account import Account
from eth_account.messages import encode_defunct

# 配置
BACKEND_URL = "http://localhost:8000"
USER_PRIVATE_KEY = "0x你的私钥"  # 用户私钥（用于签名）
USER_ADDRESS = None  # 从私钥推导

if USER_PRIVATE_KEY:
    USER_ADDRESS = Account.from_key(USER_PRIVATE_KEY).address


def sign_payment_message(
    user_address: str,
    pay_to: str,
    amount_wei: int,
    chain_id: int,
    private_key: str,
) -> str:
    """
    签名支付消息
    
    Returns:
        str: 签名（hex string）
    """
    # 创建支付消息（与 facilitator 中的格式一致）
    message_text = f"x402 Payment\nUser: {user_address}\nPayTo: {pay_to}\nAmount: {amount_wei}\nChain: {chain_id}"
    
    # 编码消息
    message_hash = encode_defunct(text=message_text)
    
    # 签名
    signed_message = Account.sign_message(message_hash, private_key)
    
    return signed_message.signature.hex()


def recharge_with_facilitator(amount: str, user_address: str = None):
    """
    使用 x402 facilitator 进行充值
    
    Args:
        amount: 充值金额（如 "1.0"）
        user_address: 用户地址（可选，如果不提供则从私钥推导）
    """
    if not USER_PRIVATE_KEY:
        print("❌ Error: USER_PRIVATE_KEY not configured")
        return
    
    if not user_address:
        user_address = USER_ADDRESS
    
    print("=" * 70)
    print("🚀 x402 Facilitator Recharge")
    print("=" * 70)
    print(f"Amount: {amount} MON")
    print(f"User Address: {user_address}")
    print("=" * 70)
    print()
    
    # Step 1: 获取支付要求
    print("[Step 1] Requesting payment requirement...")
    url = f"{BACKEND_URL}/api/v1/mcp/recharge"
    payload = {
        "amount": amount,
        "user_address": user_address,
    }
    
    response = httpx.post(url, json=payload, timeout=30)
    
    if response.status_code != 402:
        print(f"❌ Error: Expected 402, got {response.status_code}")
        print(f"Response: {response.text}")
        return
    
    payment_data = response.json()
    print(f"✅ Received 402 Payment Required")
    print(f"  - Amount: {payment_data['amount']} MON ({payment_data['amount_wei']} wei)")
    print(f"  - Pay to: {payment_data['pay_to']}")
    print(f"  - Chain ID: {payment_data['chain_id']}")
    print(f"  - Facilitator available: {payment_data.get('facilitator_available', False)}")
    print()
    
    # Step 2: 签名支付消息
    print("[Step 2] Signing payment message...")
    amount_wei = int(payment_data['amount_wei'])
    pay_to = payment_data['pay_to']
    chain_id = payment_data['chain_id']
    
    signature = sign_payment_message(
        user_address=user_address,
        pay_to=pay_to,
        amount_wei=amount_wei,
        chain_id=chain_id,
        private_key=USER_PRIVATE_KEY,
    )
    
    print(f"✅ Payment message signed")
    print(f"  - Signature: {signature[:20]}...{signature[-20:]}")
    print()
    
    # Step 3: 发送签名给 API，facilitator 自动代付
    print("[Step 3] Sending payment signature to facilitator...")
    confirm_payload = {
        "amount": amount,
        "user_address": user_address,
        "payment_signature": signature,
    }
    
    confirm_response = httpx.post(url, json=confirm_payload, timeout=60)
    
    if confirm_response.status_code == 200:
        result = confirm_response.json()
        print(f"✅ Recharge successful via x402 facilitator!")
        print(f"  - Transaction Hash: {result['tx_hash']}")
        print(f"  - New Balance: {result['new_balance']} wei")
        print(f"  - Message: {result['message']}")
    else:
        print(f"❌ Recharge failed: {confirm_response.status_code}")
        print(f"Response: {confirm_response.text}")
    
    print()
    print("=" * 70)
    print("✅ Process completed!")
    print("=" * 70)


if __name__ == "__main__":
    import sys
    
    amount = sys.argv[1] if len(sys.argv) > 1 else "1.0"
    user_address = sys.argv[2] if len(sys.argv) > 2 else None
    
    recharge_with_facilitator(amount, user_address)

