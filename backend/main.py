"""
Python后端 - 使用x402协议处理加密货币充值和余额查询
支持两种模式：
1）链上合约余额（UserBalance 合约）
2）链下 MySQL 余额（适用于 MCP tool / 前端统一充值接口）
"""
import os
import json
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from web3 import Web3
from web3.exceptions import TransactionNotFound
from eth_account import Account
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session

# 导入 x402 facilitator
try:
    from x402_facilitator import (
        settle_payment,
        create_payment_requirement,
        verify_payment_signature,
    )
    FACILITATOR_AVAILABLE = True
except ImportError:
    print("[Warning] x402_facilitator module not found, facilitator features disabled")
    FACILITATOR_AVAILABLE = False

load_dotenv()

app = FastAPI(title="x402 Payment Backend", version="1.1.0")

# CORS配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 区块链配置
RPC_URL = os.getenv("RPC_URL", "https://testnet-rpc.monad.xyz")
CONTRACT_ADDRESS = os.getenv("CONTRACT_ADDRESS", "")
MON_ADDRESS = os.getenv("MON_ADDRESS", "")  # MON ERC20代币地址（如果使用ERC20版本）
PRIVATE_KEY = os.getenv("PRIVATE_KEY", "")
CHAIN_ID = int(os.getenv("CHAIN_ID", "10143"))
TRANSIT_WALLET = os.getenv("TRANSIT_WALLET", "")  # 中转站钱包地址（接收 MON）

# 数据库配置（MySQL）
MYSQL_DSN = os.getenv(
    "MYSQL_DSN",
    "mysql+pymysql://user:password@localhost:3306/blitz_x402",
)

engine = create_engine(MYSQL_DSN, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 初始化Web3
w3 = Web3(Web3.HTTPProvider(RPC_URL))

# MON ABI (仅需要balanceOf和transferFrom，用于解析 ERC20 转账事件）
MON_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "balance", "type": "uint256"}],
        "type": "function"
    },
    {
        "constant": False,
        "inputs": [
            {"name": "_from", "type": "address"},
            {"name": "_to", "type": "address"},
            {"name": "_value", "type": "uint256"}
        ],
        "name": "transferFrom",
        "outputs": [{"name": "", "type": "bool"}],
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [
            {"name": "_owner", "type": "address"},
            {"name": "_spender", "type": "address"}
        ],
        "name": "allowance",
        "outputs": [{"name": "", "type": "uint256"}],
        "type": "function"
    }
]

mon_contract = None
if MON_ADDRESS:
    mon_contract = w3.eth.contract(
        address=Web3.to_checksum_address(MON_ADDRESS), abi=MON_ABI
    )


# ---------- Pydantic 模型 ----------
class DepositRequest(BaseModel):
    """充值请求"""
    user_address: str = Field(..., description="用户钱包地址")
    amount: str = Field(..., description="充值金额（MON，18位小数，例如：1000000000000000000表示1 MON）")
    tx_hash: Optional[str] = Field(None, description="交易哈希（x402支付后提供）")
    payment_proof: Optional[str] = Field(None, description="x402支付证明")


class BalanceQuery(BaseModel):
    """余额查询请求"""
    user_address: str = Field(..., description="用户钱包地址")


class DepositResponse(BaseModel):
    """充值响应"""
    success: bool
    message: str
    tx_hash: Optional[str] = None
    new_balance: Optional[str] = None


class BalanceResponse(BaseModel):
    """余额查询响应"""
    user_address: str
    balance: str
    balance_mon: str  # 格式化后的MON余额（除以1e18）


class X402PaymentRequest(BaseModel):
    """x402支付请求"""
    user_address: str
    amount: str
    payment_data: dict  # x402支付数据


class X402QuoteRequest(BaseModel):
    """x402 报价请求（MCP / 前端通用）"""

    user_address: str = Field(..., description="用户钱包地址")
    amount: str = Field(..., description="充值金额（人类可读，如 1.0 或 0.5）")
    client_type: str = Field("mcp", description="调用方类型：mcp / web 等")


class X402QuoteResponse(BaseModel):
    """x402 报价响应"""

    price_wei: str
    chain_id: int
    token: str
    pay_to: str
    description: str


class MCPDepositConfirm(BaseModel):
    """MCP / 前端 充值确认，请求体（用于直接提供 tx_hash 的场景）"""

    user_address: str
    amount_wei: str = Field(..., description="充值金额，单位 wei（18 位）")
    tx_hash: str
    client_type: str = Field("mcp", description="mcp / web")


class MCPRechargeRequest(BaseModel):
    """MCP tool 充值请求（通过 x402）"""

    user_address: str = Field(
        default="0xb1fD9C228aeF736B25140049f774b3b99456c10D",
        description="用户钱包地址（默认值：0xb1fD9C228aeF736B25140049f774b3b99456c10D）"
    )
    amount: str = Field(..., description="充值金额（人类可读，如 1.0）")
    tx_hash: Optional[str] = Field(None, description="链上交易哈希（x402 支付后提供）")
    private_key: Optional[str] = Field(None, description="用户私钥（可选，如果提供则自动完成支付）")
    payment_signature: Optional[str] = Field(None, description="x402 支付签名（用于 facilitator 代付）")
    payment_id: Optional[str] = Field(None, description="支付请求唯一标识符（用于防重放，可选）")
    payment_data: Optional[dict] = Field(None, description="完整的支付数据对象（包含 signature、id 等，可选）")


class InternalRecharge(BaseModel):
    """提供给 x402 网关（Node/TS）调用的内部充值接口请求体"""

    user_address: str
    amount: str = Field(..., description="充值金额（人类可读 MON 数量，如 1.0）")
    client_type: str = Field("x402-gateway", description="调用方类型")


# 工具函数
def wei_to_mon(wei_amount: int) -> str:
    """将wei转换为MON（18位小数）"""
    return str(wei_amount / 1e18)


def mon_to_wei(mon_amount: str) -> int:
    """将MON转换为wei（18位小数）"""
    return int(float(mon_amount) * 1e18)


def verify_transaction(tx_hash: str) -> dict:
    """验证交易并获取交易详情"""
    try:
        receipt = w3.eth.get_transaction_receipt(tx_hash)
        if receipt.status != 1:
            raise HTTPException(status_code=400, detail="Transaction failed")
        return receipt
    except TransactionNotFound:
        raise HTTPException(status_code=404, detail="Transaction not found")


def check_mon_transfer(tx_hash: str, from_address: str, to_address: str, amount: int) -> bool:
    """检查MON转账是否成功（支持原生MON和ERC20 MON）"""
    try:
        # 获取交易收据（如果交易未确认，会抛出异常）
        try:
            receipt = w3.eth.get_transaction_receipt(tx_hash)
        except Exception as e:
            print(f"Transaction not found or not confirmed: {e}")
            return False
        
        # 检查交易状态
        if receipt.status != 1:
            print(f"Transaction failed with status: {receipt.status}")
            return False
        
        # 检查原生MON转账（value > 0）
        tx = w3.eth.get_transaction(tx_hash)
        if tx.value >= amount and tx.to and tx.to.lower() == to_address.lower():
            if tx['from'].lower() == from_address.lower():
                print(f"Native MON transfer verified: {tx.value} wei from {from_address} to {to_address}")
                return True
        
        # 检查ERC20 MON转账（如果有MON_ADDRESS配置）
        if MON_ADDRESS:
            # 解析日志查找MON Transfer事件
            # Transfer(address indexed from, address indexed to, uint256 value)
            transfer_topic = w3.keccak(text="Transfer(address,address,uint256)".encode()).hex()
            
            for log in receipt.logs:
                if log.address.lower() == MON_ADDRESS.lower():
                    if len(log.topics) >= 3:
                        # 检查是否是Transfer事件
                        if log.topics[0].hex() == transfer_topic:
                            log_from = "0x" + log.topics[1].hex()[-40:]
                            log_to = "0x" + log.topics[2].hex()[-40:]
                            
                            if (log_from.lower() == from_address.lower() and 
                                log_to.lower() == to_address.lower()):
                                # 解析金额
                                transfer_amount = int(log.data.hex(), 16)
                                if transfer_amount >= amount:
                                    print(f"ERC20 MON transfer verified: {transfer_amount} wei from {from_address} to {to_address}")
                                    return True
        print(f"MON transfer verification failed: no matching transfer found")
        return False
    except Exception as e:
        print(f"Error checking MON transfer: {e}")
        return False


def get_db() -> Session:
    """获取一个数据库 Session，上层用 try/finally 关闭"""
    return SessionLocal()


# API端点
@app.get("/")
async def root():
    """根端点"""
    return {
        "message": "x402 Payment Backend API",
        "version": "1.1.0",
        "contract_address": CONTRACT_ADDRESS,
        "chain_id": CHAIN_ID
    }


@app.get("/health")
async def health_check():
    """健康检查"""
    try:
        block_number = w3.eth.block_number
        # 简单检查数据库连通性
        db_ok = True
        try:
            db = get_db()
            db.execute(text("SELECT 1"))
            db.close()
        except Exception:
            db_ok = False

        return {
            "status": "healthy",
            "chain_id": CHAIN_ID,
            "latest_block": block_number,
            "db_ok": db_ok,
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e)
        }


@app.post("/api/v1/x402/quote", response_model=X402QuoteResponse)
async def x402_quote(request: X402QuoteRequest):
    """
    x402 报价接口
    MCP tool 与前端都可以调用，用于获取需要支付的金额和收款地址（中转站钱包）。
    """
    if not TRANSIT_WALLET:
        raise HTTPException(status_code=500, detail="TRANSIT_WALLET not configured")

    try:
        # 这里简单把 amount 当作 MON 的人类可读数字，例如 "1.0"
        amount_wei = mon_to_wei(request.amount)
        if amount_wei <= 0:
            raise HTTPException(status_code=400, detail="Invalid amount")

        return X402QuoteResponse(
            price_wei=str(amount_wei),
            chain_id=CHAIN_ID,
            token="MON",
            pay_to=Web3.to_checksum_address(TRANSIT_WALLET),
            description="Recharge MON balance via x402",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid amount format: {e}")


def send_mon_transaction(
    from_address: str,
    to_address: str,
    amount_wei: int,
    private_key: str,
) -> dict:
    """
    发送 MON 转账交易
    
    Returns:
        dict: {
            "success": bool,
            "tx_hash": str,
            "error": str (如果失败)
        }
    """
    try:
        account = Account.from_key(private_key)
        sender_address = account.address
        
        # 验证地址匹配
        if from_address.lower() != sender_address.lower():
            return {
                "success": False,
                "error": f"Private key address ({sender_address}) doesn't match user_address ({from_address})"
            }
        
        # 检查余额
        balance_wei = w3.eth.get_balance(sender_address)
        estimated_gas = 21000
        gas_price = w3.eth.gas_price
        total_cost = amount_wei + (estimated_gas * gas_price)
        
        if balance_wei < total_cost:
            return {
                "success": False,
                "error": f"Insufficient balance. Need {wei_to_mon(total_cost)} MON (including gas), but have {wei_to_mon(balance_wei)} MON"
            }
        
        # 构建交易
        nonce = w3.eth.get_transaction_count(sender_address)
        transaction = {
            "to": Web3.to_checksum_address(to_address),
            "value": amount_wei,
            "gas": estimated_gas,
            "gasPrice": gas_price,
            "nonce": nonce,
            "chainId": CHAIN_ID,
        }
        
        # 签名并发送
        signed_txn = account.sign_transaction(transaction)
        tx_hash = w3.eth.send_raw_transaction(signed_txn.rawTransaction)
        tx_hash_hex = tx_hash.hex()
        
        print(f"[Auto Payment] Transaction sent: {tx_hash_hex}")
        
        # 等待确认
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        
        if receipt.status == 1:
            return {
                "success": True,
                "tx_hash": tx_hash_hex,
                "block_number": receipt.blockNumber
            }
        else:
            return {
                "success": False,
                "error": "Transaction reverted"
            }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@app.post("/api/v1/mcp/recharge", response_model=DepositResponse)
async def mcp_recharge(request: MCPRechargeRequest):
    """
    MCP tool 充值接口（通过 x402，集成自建 facilitator）
    
    流程：
    1. 如果提供了 payment_signature，使用 x402 facilitator 验证签名并代付（推荐）
    2. 如果提供了 private_key，自动完成链上支付并确认充值
    3. 如果提供了 tx_hash，验证交易并确认充值
    4. 如果都没有提供，返回 402 支付要求
    
    此接口确保充值流程完整执行，包括：
    - x402 facilitator 支付签名验证和代付
    - 链上交易验证（确保交易已确认且金额正确）
    - 数据库余额更新（原子操作）
    - 充值记录写入（支持幂等）
    """
    if not TRANSIT_WALLET:
        raise HTTPException(status_code=500, detail="TRANSIT_WALLET not configured")
    
    try:
        # 1. 参数验证
        user_address = Web3.to_checksum_address(request.user_address)
        amount_wei = mon_to_wei(request.amount)
        
        if amount_wei <= 0:
            raise HTTPException(status_code=400, detail="Invalid amount: amount must be greater than 0")
        
        # 2. 支付逻辑
        tx_hash = None
        payment_result = None
        auto_paid_by_service = False  # 标记是否由服务账户代付
        paid_by_facilitator = False  # 标记是否由 facilitator 代付
        
        # 2.0 如果提供了 payment_signature 或 payment_data，使用 x402 facilitator 代付（推荐方式）
        payment_signature = None
        payment_id = None
        
        # 支持两种方式：直接提供 payment_signature，或通过 payment_data 对象提供
        if request.payment_data:
            # 从 payment_data 对象中提取签名和 ID
            payment_signature = request.payment_data.get("signature") or request.payment_data.get("payment_signature")
            payment_id = request.payment_data.get("id") or request.payment_data.get("payment_id")
        else:
            # 直接提供 payment_signature
            payment_signature = request.payment_signature
            payment_id = request.payment_id
        
        if payment_signature and FACILITATOR_AVAILABLE:
            print(f"[x402 Facilitator] Payment signature provided, using facilitator to settle payment")
            if payment_id:
                print(f"[x402 Facilitator] Payment ID: {payment_id}")
            
            # 调用 facilitator 结算支付
            facilitator_result = settle_payment(
                user_address=user_address,
                pay_to=TRANSIT_WALLET,
                amount_wei=amount_wei,
                payment_signature=payment_signature,
                payment_id=payment_id,
                chain_id=CHAIN_ID,
            )
            
            if not facilitator_result["success"]:
                raise HTTPException(
                    status_code=400,
                    detail=f"Facilitator payment failed: {facilitator_result.get('error', 'Unknown error')}"
                )
            
            tx_hash = facilitator_result["tx_hash"]
            paid_by_facilitator = True
            print(f"[x402 Facilitator] Payment settled successfully, tx_hash={tx_hash}")
        
        # 2.1 如果用户提供了 private_key，使用用户私钥支付
        elif request.private_key:
            print(f"[Auto Recharge] User private key provided, using user wallet for payment")
            payment_result = send_mon_transaction(
                from_address=user_address,
                to_address=TRANSIT_WALLET,
                amount_wei=amount_wei,
                private_key=request.private_key,
            )
            
            if not payment_result["success"]:
                raise HTTPException(
                    status_code=400,
                    detail=f"Auto payment failed: {payment_result.get('error', 'Unknown error')}"
                )
            
            tx_hash = payment_result["tx_hash"]
            print(f"[Auto Recharge] Payment successful with user wallet, tx_hash={tx_hash}")
        
        # 2.2 如果用户没有提供 private_key 和 tx_hash，且后端配置了 PRIVATE_KEY，使用服务账户自动代付
        elif not request.tx_hash and PRIVATE_KEY:
            print(f"[Auto Recharge] No user private key or tx_hash provided, using service account for auto payment")
            
            # 使用服务账户的私钥代付
            service_account = Account.from_key(PRIVATE_KEY)
            service_address = service_account.address
            
            print(f"[Auto Recharge] Service account: {service_address}, paying for user: {user_address}")
            
            payment_result = send_mon_transaction(
                from_address=service_address,  # 从服务账户支付
                to_address=TRANSIT_WALLET,
                amount_wei=amount_wei,
                private_key=PRIVATE_KEY,
            )
            
            if not payment_result["success"]:
                raise HTTPException(
                    status_code=400,
                    detail=f"Service account auto payment failed: {payment_result.get('error', 'Unknown error')}"
                )
            
            tx_hash = payment_result["tx_hash"]
            auto_paid_by_service = True
            print(f"[Auto Recharge] Service account payment successful, tx_hash={tx_hash}")
        
        # 3. 如果提供了 tx_hash，或者通过自动支付获得了 tx_hash，验证交易并完成充值
        if request.tx_hash:
            tx_hash = request.tx_hash
        elif payment_result and payment_result.get("tx_hash"):
            tx_hash = payment_result["tx_hash"]
        
        if tx_hash:
            
            print(f"[Recharge] Processing recharge: user={user_address}, amount={amount_wei} wei, tx_hash={tx_hash}")
            
            # 3.1 验证链上 MON 转账
            # 如果是由 facilitator 代付，验证 facilitator 账户到 TRANSIT_WALLET 的转账
            # 如果是由服务账户代付，验证服务账户到 TRANSIT_WALLET 的转账
            # 如果是由用户支付，验证用户到 TRANSIT_WALLET 的转账
            if paid_by_facilitator:
                # Facilitator 代付，验证 facilitator 账户的转账
                from x402_facilitator import FACILITATOR_ADDRESS
                if FACILITATOR_ADDRESS:
                    if not check_mon_transfer(tx_hash, FACILITATOR_ADDRESS, TRANSIT_WALLET, amount_wei):
                        raise HTTPException(
                            status_code=400,
                            detail=f"Facilitator payment verification failed. Please ensure:\n"
                                   f"1. Transaction {tx_hash} is confirmed on chain\n"
                                   f"2. Transaction is from facilitator ({FACILITATOR_ADDRESS}) to {TRANSIT_WALLET}\n"
                                   f"3. Transaction amount >= {amount_wei} wei ({request.amount} MON)",
                        )
                    print(f"[Recharge] Facilitator payment verified: {FACILITATOR_ADDRESS} -> {TRANSIT_WALLET}")
            elif auto_paid_by_service:
                # 服务账户代付，验证服务账户的转账
                service_account = Account.from_key(PRIVATE_KEY)
                service_address = service_account.address
                if not check_mon_transfer(tx_hash, service_address, TRANSIT_WALLET, amount_wei):
                    raise HTTPException(
                        status_code=400,
                        detail=f"Service account payment verification failed. Please ensure:\n"
                               f"1. Transaction {tx_hash} is confirmed on chain\n"
                               f"2. Transaction is from service account ({service_address}) to {TRANSIT_WALLET}\n"
                               f"3. Transaction amount >= {amount_wei} wei ({request.amount} MON)",
                    )
                print(f"[Recharge] Service account payment verified: {service_address} -> {TRANSIT_WALLET}")
            else:
                # 用户支付，验证用户的转账
                if not check_mon_transfer(tx_hash, user_address, TRANSIT_WALLET, amount_wei):
                    raise HTTPException(
                        status_code=400,
                        detail=f"MON transfer verification failed. Please ensure:\n"
                               f"1. Transaction {tx_hash} is confirmed on chain\n"
                               f"2. Transaction is from {user_address} to {TRANSIT_WALLET}\n"
                               f"3. Transaction amount >= {amount_wei} wei ({request.amount} MON)",
                    )
            
            print(f"[Recharge] Transaction verified successfully: {tx_hash}")
            
            # 3.2 在数据库中更新余额 + 写流水（幂等，原子操作）
            db = get_db()
            try:
                # 检查是否已经处理过该交易（幂等性保证）
                existing = db.execute(
                    text(
                        "SELECT id FROM recharge_records "
                        "WHERE user_address = :u AND tx_hash = :h AND status = 'success'"
                    ),
                    {"u": user_address, "h": tx_hash},
                ).first()
                
                if existing:
                    print(f"[Recharge] Transaction already processed: {tx_hash}")
                    row = db.execute(
                        text("SELECT balance FROM user_balances WHERE user_address = :u"),
                        {"u": user_address},
                    ).first()
                    balance = int(row[0]) if row else 0
                    return DepositResponse(
                        success=True,
                        message="Already processed (idempotent)",
                        tx_hash=tx_hash,
                        new_balance=str(balance),
                    )
                
                # 开始事务：写入充值记录（pending）
                db.execute(
                    text(
                        "INSERT INTO recharge_records "
                        "(user_address, amount, tx_hash, client_type, status) "
                        "VALUES (:u, :a, :h, :c, 'pending')"
                    ),
                    {
                        "u": user_address,
                        "a": amount_wei,
                        "h": tx_hash,
                        "c": "mcp",
                    },
                )
                print(f"[Recharge] Recharge record created (pending): user={user_address}, amount={amount_wei}")
                
                # 更新 / 插入用户余额（原子操作）
                db.execute(
                    text(
                        "INSERT INTO user_balances (user_address, balance) "
                        "VALUES (:u, :a) "
                        "ON DUPLICATE KEY UPDATE balance = balance + VALUES(balance)"
                    ),
                    {"u": user_address, "a": amount_wei},
                )
                print(f"[Recharge] User balance updated: user={user_address}, added={amount_wei}")
                
                # 标记充值记录为 success
                db.execute(
                    text(
                        "UPDATE recharge_records SET status = 'success' "
                        "WHERE user_address = :u AND tx_hash = :h"
                    ),
                    {"u": user_address, "h": tx_hash},
                )
                print(f"[Recharge] Recharge record marked as success: tx_hash={tx_hash}")
                
                # 查询新余额
                row = db.execute(
                    text("SELECT balance FROM user_balances WHERE user_address = :u"),
                    {"u": user_address},
                ).first()
                balance = int(row[0]) if row else 0
                
                # 提交事务
                db.commit()
                print(f"[Recharge] Recharge completed successfully: user={user_address}, new_balance={balance}")
                
                message = "Recharge successful via x402"
                if paid_by_facilitator:
                    message += " (x402 facilitator payment)"
                elif request.private_key:
                    message += " (user auto payment)"
                elif auto_paid_by_service:
                    message += " (service account auto payment)"
                
                return DepositResponse(
                    success=True,
                    message=message,
                    tx_hash=tx_hash,
                    new_balance=str(balance),
                )
            except Exception as db_error:
                db.rollback()
                print(f"[Recharge] Database error, rolled back: {db_error}")
                raise HTTPException(
                    status_code=500,
                    detail=f"Database operation failed: {str(db_error)}"
                )
            finally:
                db.close()
        
        # 4. 如果都没有提供，返回 402 支付要求（x402 协议标准）
        from fastapi.responses import JSONResponse
        
        # 使用 facilitator 创建支付要求（如果可用）
        if FACILITATOR_AVAILABLE:
            payment_req = create_payment_requirement(
                amount=request.amount,
                pay_to=TRANSIT_WALLET,
                user_address=user_address,
                chain_id=CHAIN_ID,
            )
            return JSONResponse(
                status_code=402,
                content=payment_req,
                headers={
                    "X-Payment-Required": "true",
                    "X-Payment-Amount": str(amount_wei),
                    "X-Payment-Token": "MON",
                    "X-Payment-To": TRANSIT_WALLET,
                }
            )
        else:
            # 降级到传统方式
            return JSONResponse(
                status_code=402,
                content={
                    "payment_required": True,
                    "amount": request.amount,
                    "amount_wei": str(amount_wei),
                    "chain_id": CHAIN_ID,
                    "token": "MON",
                    "pay_to": Web3.to_checksum_address(TRANSIT_WALLET),
                    "user_address": user_address,
                    "description": "Please send MON to the transit wallet and provide tx_hash",
                    "instructions": "Send MON transaction from your wallet to TRANSIT_WALLET, then call this endpoint again with tx_hash. Or provide payment_signature for facilitator payment."
                },
                headers={
                    "X-Payment-Required": "true",
                    "X-Payment-Amount": str(amount_wei),
                    "X-Payment-Token": "MON",
                    "X-Payment-To": TRANSIT_WALLET,
                }
            )
            
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid address or amount format: {str(e)}")
    except Exception as e:
        print(f"[Recharge] Unexpected error: {e}")
        raise HTTPException(status_code=500, detail=f"Recharge failed: {str(e)}")


@app.post("/internal/recharge")
async def internal_recharge(request: InternalRecharge):
    """
    内部充值接口
    - 仅供 x402 网关服务调用
    - 假定支付已经由 thirdweb x402 完成并校验
    - 这里只负责在 MySQL 中更新用户余额
    """
    try:
        user = Web3.to_checksum_address(request.user_address)
        amount_wei = mon_to_wei(request.amount)
        if amount_wei <= 0:
            raise HTTPException(status_code=400, detail="Invalid amount")

        db = get_db()
        try:
            db.execute(
                text(
                    "INSERT INTO user_balances (user_address, balance) "
                    "VALUES (:u, :a) "
                    "ON DUPLICATE KEY UPDATE balance = balance + VALUES(balance)"
                ),
                {"u": user, "a": amount_wei},
            )
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal recharge failed: {e}")


@app.post("/api/v1/mcp/deposit-confirm", response_model=DepositResponse)
async def mcp_deposit_confirm(request: MCPDepositConfirm):
    """
    MCP tool / 前端 通用充值确认接口。
    步骤：
    1. 校验链上 tx_hash 确实是 user -> TRANSIT_WALLET 的 MON 转账，金额 >= amount_wei
    2. 在 MySQL 中原子更新 user_balances 表
    3. 记录一条 recharge_records 流水，确保幂等
    """
    if not TRANSIT_WALLET:
        raise HTTPException(status_code=500, detail="TRANSIT_WALLET not configured")

    try:
        user = Web3.to_checksum_address(request.user_address)
        amount_wei = int(request.amount_wei)
        if amount_wei <= 0:
            raise HTTPException(status_code=400, detail="Invalid amount_wei")

        # 1. 校验链上 MON 转账
        if not check_mon_transfer(request.tx_hash, user, TRANSIT_WALLET, amount_wei):
            raise HTTPException(
                status_code=400,
                detail="MON transfer verification failed",
            )

        # 2. 在数据库中更新余额 + 写流水（幂等）
        db = get_db()
        try:
            # 检查是否已经处理过该交易（幂等）
            existing = db.execute(
                text(
                    "SELECT id FROM recharge_records "
                    "WHERE user_address = :u AND tx_hash = :h AND status = 'success'"
                ),
                {"u": user, "h": request.tx_hash},
            ).first()

            if existing:
                row = db.execute(
                    text(
                        "SELECT balance FROM user_balances WHERE user_address = :u"
                    ),
                    {"u": user},
                ).first()
                balance = row[0] if row else 0
                return DepositResponse(
                    success=True,
                    message="Already processed",
                    tx_hash=request.tx_hash,
                    new_balance=str(balance),
                )

            # 写入充值记录（pending）
            db.execute(
                text(
                    "INSERT INTO recharge_records "
                    "(user_address, amount, tx_hash, client_type, status) "
                    "VALUES (:u, :a, :h, :c, 'pending')"
                ),
                {
                    "u": user,
                    "a": amount_wei,
                    "h": request.tx_hash,
                    "c": request.client_type,
                },
            )

            # 更新 / 插入用户余额
            db.execute(
                text(
                    "INSERT INTO user_balances (user_address, balance) "
                    "VALUES (:u, :a) "
                    "ON DUPLICATE KEY UPDATE balance = balance + VALUES(balance)"
                ),
                {"u": user, "a": amount_wei},
            )

            # 标记充值记录为 success
            db.execute(
                text(
                    "UPDATE recharge_records SET status = 'success' "
                    "WHERE user_address = :u AND tx_hash = :h"
                ),
                {"u": user, "h": request.tx_hash},
            )

            # 查询新余额
            row = db.execute(
                text(
                    "SELECT balance FROM user_balances WHERE user_address = :u"
                ),
                {"u": user},
            ).first()
            balance = row[0] if row else 0

            db.commit()

            return DepositResponse(
                success=True,
                message="Deposit successful",
                tx_hash=request.tx_hash,
                new_balance=str(balance),
            )
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Deposit confirm failed: {e}")
@app.post("/api/v1/balance", response_model=BalanceResponse)
async def get_balance(request: BalanceQuery):
    """
    查询用户余额（链下 MySQL）
    """
    try:
        user_address = Web3.to_checksum_address(request.user_address)

        db = get_db()
        try:
            row = db.execute(
                text(
                    "SELECT balance FROM user_balances WHERE user_address = :u"
                ),
                {"u": user_address},
            ).first()
        finally:
            db.close()

        balance_wei = int(row[0]) if row else 0
        balance_mon = wei_to_mon(balance_wei)

        return BalanceResponse(
            user_address=user_address,
            balance=str(balance_wei),
            balance_mon=balance_mon,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid address: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Query failed: {str(e)}")


@app.get("/api/v1/balance/{user_address}", response_model=BalanceResponse)
async def get_balance_get(user_address: str):
    """
    查询用户余额（GET方式）
    """
    return await get_balance(BalanceQuery(user_address=user_address))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

