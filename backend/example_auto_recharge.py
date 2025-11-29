#!/usr/bin/env python3
"""
简单的自动化充值示例

这个脚本展示了如何：
1. 解析 402 响应
2. 自动完成链上支付
3. 确认充值

可以直接运行，或者作为参考代码
"""

import os
import json
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
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")


def mon_to_wei(mon_amount: str) -> int:
    """将MON转换为wei"""
    return int(Decimal(mon_amount) * Decimal(10**18))


def auto_recharge(amount: str, user_address: str = None):
    """
    自动化充值流程
    
    Args:
        amount: 充值金额（如 "1.0"）
        user_address: 用户地址（可选，如果不提供则从私钥推导）
    """
    print("="*70)
    print("🚀 开始自动化充值流程")
    print("="*70)
    
    # 1. 获取支付要求（402 响应）
    print("\n[步骤 1] 获取支付要求...")
    url = f"{BACKEND_URL}/api/v1/mcp/recharge"
    payload = {"amount": amount}
    if user_address:
        payload["user_address"] = user_address
    
    response = httpx.post(url, json=payload, timeout=30)
    
    if response.status_code != 402:
        print(f"❌ 错误: 期望 402 状态码，但收到 {response.status_code}")
        print(f"响应: {response.text}")
        return
    
    payment_data = response.json()
    print(f"✅ 收到支付要求:")
    print(f"   - 金额: {payment_data['amount']} MON ({payment_data['amount_wei']} wei)")
    print(f"   - 收款地址: {payment_data['pay_to']}")
    print(f"   - 链 ID: {payment_data['chain_id']}")
    
    # 2. 准备链上支付
    print("\n[步骤 2] 准备链上支付...")
    
    if not PRIVATE_KEY:
        print("❌ 错误: 未配置 PRIVATE_KEY，请在 .env 文件中设置")
        return
    
    # 从私钥获取账户
    account = Account.from_key(PRIVATE_KEY)
    sender_address = account.address
    
    if user_address and user_address.lower() != sender_address.lower():
        print(f"⚠️  警告: 私钥地址 ({sender_address}) 与指定地址 ({user_address}) 不匹配")
        print(f"将使用私钥地址: {sender_address}")
    
    # 初始化 Web3
    w3 = Web3(Web3.HTTPProvider(RPC_URL))
    if not w3.is_connected():
        print(f"❌ 错误: 无法连接到 RPC: {RPC_URL}")
        return
    
    # 检查余额
    balance_wei = w3.eth.get_balance(sender_address)
    amount_wei = int(payment_data['amount_wei'])
    pay_to = Web3.to_checksum_address(payment_data['pay_to'])
    
    print(f"   - 发送方: {sender_address}")
    print(f"   - 接收方: {pay_to}")
    print(f"   - 余额: {balance_wei / 1e18:.6f} MON")
    
    # 估算 Gas
    estimated_gas = 21000
    gas_price = w3.eth.gas_price
    total_cost = amount_wei + (estimated_gas * gas_price)
    
    if balance_wei < total_cost:
        print(f"❌ 余额不足: 需要 {total_cost / 1e18:.6f} MON (含 Gas)，但只有 {balance_wei / 1e18:.6f} MON")
        return
    
    # 3. 发送交易
    print("\n[步骤 3] 发送链上交易...")
    
    nonce = w3.eth.get_transaction_count(sender_address)
    transaction = {
        "to": pay_to,
        "value": amount_wei,
        "gas": estimated_gas,
        "gasPrice": gas_price,
        "nonce": nonce,
        "chainId": CHAIN_ID,
    }
    
    signed_txn = account.sign_transaction(transaction)
    tx_hash = w3.eth.send_raw_transaction(signed_txn.rawTransaction)
    tx_hash_hex = tx_hash.hex()
    
    print(f"✅ 交易已发送: {tx_hash_hex}")
    
    # 4. 等待确认
    print("\n[步骤 4] 等待交易确认...")
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
    
    if receipt.status != 1:
        print(f"❌ 交易失败")
        return
    
    print(f"✅ 交易已确认，区块: {receipt.blockNumber}")
    
    # 5. 确认充值
    print("\n[步骤 5] 确认充值...")
    confirm_payload = {
        "user_address": sender_address,
        "amount": amount,
        "tx_hash": tx_hash_hex
    }
    
    confirm_response = httpx.post(url, json=confirm_payload, timeout=30)
    
    if confirm_response.status_code == 200:
        result = confirm_response.json()
        print(f"✅ 充值成功!")
        print(f"   - 交易哈希: {tx_hash_hex}")
        print(f"   - 新余额: {result.get('new_balance')} wei ({int(result.get('new_balance', 0)) / 1e18:.6f} MON)")
        print(f"   - 消息: {result.get('message')}")
    else:
        print(f"❌ 确认失败: {confirm_response.status_code}")
        print(f"响应: {confirm_response.text}")
    
    print("\n" + "="*70)
    print("✅ 充值流程完成!")
    print("="*70)


if __name__ == "__main__":
    import sys
    
    # 从命令行参数获取金额和地址
    amount = sys.argv[1] if len(sys.argv) > 1 else "1.0"
    user_address = sys.argv[2] if len(sys.argv) > 2 else None
    
    print(f"充值金额: {amount} MON")
    if user_address:
        print(f"用户地址: {user_address}")
    print()
    
    auto_recharge(amount, user_address)

