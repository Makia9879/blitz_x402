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
    """MCP / 前端 充值确认，请求体"""

    user_address: str
    amount_wei: str = Field(..., description="充值金额，单位 wei（18 位）")
    tx_hash: str
    client_type: str = Field("mcp", description="mcp / web")


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
        receipt = w3.eth.get_transaction_receipt(tx_hash)
        if receipt.status != 1:
            return False
        
        # 检查原生MON转账（value > 0）
        tx = w3.eth.get_transaction(tx_hash)
        if tx.value >= amount and tx.to and tx.to.lower() == to_address.lower():
            if tx['from'].lower() == from_address.lower():
                return True
        
        # 检查ERC20 MON转账（如果有MON_ADDRESS配置）
        if MON_ADDRESS:
            # 解析日志查找MON Transfer事件
            # Transfer(address indexed from, address indexed to, uint256 value)
            transfer_topic = w3.keccak(text="Transfer(address,address,uint256)").hex()
            
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
                                    return True
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

