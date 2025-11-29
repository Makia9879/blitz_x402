"""
Python后端 - 使用x402协议处理加密货币充值和余额查询
支持两种模式：
1）链上合约余额（UserBalance 合约）
2）链下 MySQL 余额（适用于 MCP tool / 前端统一充值接口）
"""
import os
import json
from typing import Optional, Union
from decimal import Decimal

from fastapi import FastAPI, HTTPException, Request, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from web3 import Web3
from web3.exceptions import TransactionNotFound
from eth_account import Account
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
import httpx

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

# Claude API 代理配置
CLAUDE_BACKEND_URL = os.getenv("CLAUDE_BACKEND_URL", "")
CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY", "")
MON_TO_TOKEN_RATE = int(os.getenv("MON_TO_TOKEN_RATE", "100000"))  # 1 MON = 10万 tokens
MAX_TOKENS_PER_REQUEST = int(os.getenv("MAX_TOKENS_PER_REQUEST", "8192"))
CLAUDE_REQUEST_TIMEOUT = int(os.getenv("CLAUDE_REQUEST_TIMEOUT", "300"))  # 秒
DEFAULT_TEST_ADDRESS = os.getenv("DEFAULT_TEST_ADDRESS", "")  # 测试用默认地址（可选）
SKIP_BALANCE_CHECK = os.getenv("SKIP_BALANCE_CHECK", "false").lower() == "true"  # 是否跳过余额检查

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


# ========== Claude API 代理相关模型 ==========

class ClaudeMessage(BaseModel):
    """Claude 消息"""
    role: str
    content: str


class ClaudeMessageRequest(BaseModel):
    """Claude API 请求（兼容 Claude API 格式）"""
    model_config = {"extra": "allow"}  # 允许额外字段，确保兼容 Claude API 的所有参数

    model: str
    messages: list[dict]
    max_tokens: Optional[int] = 4096
    temperature: Optional[float] = 1.0
    stream: Optional[bool] = False
    system: Optional[Union[str, list[dict]]] = None  # 支持字符串或数组格式（prompt caching）
    metadata: Optional[dict] = None
    stop_sequences: Optional[list[str]] = None
    top_p: Optional[float] = None
    top_k: Optional[int] = None
    tools: Optional[list[dict]] = None
    tool_choice: Optional[dict] = None


class ClaudeUsageInfo(BaseModel):
    """Token 使用统计"""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: Optional[int] = 0
    cache_read_input_tokens: Optional[int] = 0


class ClaudeErrorResponse(BaseModel):
    """Claude 代理错误响应"""
    error: str
    message: str
    current_balance_mon: Optional[str] = None
    required_mon: Optional[str] = None


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


# ========== Claude API 代理相关函数 ==========

async def check_and_deduct_balance(
    user_address: str,
    max_tokens: int,
    db: Session
) -> tuple[bool, Optional[str], Optional[Decimal]]:
    """
    检查余额并预扣费

    Args:
        user_address: 用户钱包地址
        max_tokens: 请求的最大 tokens
        db: 数据库 Session

    Returns:
        (成功标志, 错误信息, 当前余额 MON)
    """
    # 1. 地址标准化
    try:
        user_address = Web3.to_checksum_address(user_address)
    except Exception as e:
        return False, f"Invalid address: {str(e)}", None

    # 2. 计算预估消耗（加 20% 安全系数）
    estimated_tokens = max_tokens * 1.2
    estimated_mon_wei = int((estimated_tokens / MON_TO_TOKEN_RATE) * 1e18)

    # 3. 查询当前余额
    result = db.execute(
        text("SELECT balance FROM user_balances WHERE user_address = :addr"),
        {"addr": user_address}
    ).fetchone()

    if not result:
        return False, "User balance not found", None

    current_balance = result[0]
    current_balance_mon = Decimal(current_balance) / Decimal(1e18)

    # 4. 检查余额
    if current_balance < estimated_mon_wei:
        return False, "Insufficient balance", current_balance_mon

    # 5. 原子扣除余额
    update_result = db.execute(
        text(
            "UPDATE user_balances "
            "SET balance = balance - :amount "
            "WHERE user_address = :addr AND balance >= :amount"
        ),
        {"addr": user_address, "amount": estimated_mon_wei}
    )
    db.commit()

    if update_result.rowcount == 0:
        return False, "Balance deduction failed (concurrent access)", current_balance_mon

    return True, None, current_balance_mon


def parse_sse_usage(line: str) -> Optional[dict]:
    """
    从 SSE 事件中解析 usage 数据

    支持：
    - message_start: 输入 tokens 和缓存 tokens
    - message_delta: 输出 tokens

    Args:
        line: SSE 事件行

    Returns:
        解析的 usage 数据或 None
    """
    if not line.startswith("data:"):
        return None

    json_str = line[5:].strip()
    if not json_str or json_str == "[DONE]":
        return None

    try:
        data = json.loads(json_str)

        # message_start 事件
        if data.get("type") == "message_start":
            usage = data.get("message", {}).get("usage", {})
            return {
                "type": "start",
                "input_tokens": usage.get("input_tokens", 0),
                "cache_creation_input_tokens": usage.get("cache_creation_input_tokens", 0),
                "cache_read_input_tokens": usage.get("cache_read_input_tokens", 0),
            }

        # message_delta 事件
        elif data.get("type") == "message_delta":
            usage = data.get("usage", {})
            if "output_tokens" in usage:
                return {
                    "type": "delta",
                    "output_tokens": usage["output_tokens"]
                }

    except json.JSONDecodeError:
        pass

    return None


async def _log_usage(user_address: str, usage: dict):
    """
    记录真实的 token usage

    可选功能：
    - 保存到新表 claude_usage_logs
    - 用于后续分析和对账

    Args:
        user_address: 用户地址
        usage: usage 数据
    """
    try:
        total_tokens = (
            usage.get("input_tokens", 0) +
            usage.get("output_tokens", 0) +
            usage.get("cache_creation_input_tokens", 0) +
            usage.get("cache_read_input_tokens", 0)
        )

        print(f"📊 Usage logged for {user_address}: {total_tokens} tokens")
        print(f"   Input: {usage.get('input_tokens', 0)}, Output: {usage.get('output_tokens', 0)}")
        print(f"   Cache Create: {usage.get('cache_creation_input_tokens', 0)}, Cache Read: {usage.get('cache_read_input_tokens', 0)}")

        # TODO: 可以插入到数据库表以便后续分析
        # db = get_db()
        # try:
        #     db.execute(text("INSERT INTO claude_usage_logs ..."))
        #     db.commit()
        # finally:
        #     db.close()
    except Exception as e:
        print(f"⚠️  Failed to log usage: {e}")


async def _non_stream_proxy(
    backend_url: str,
    request_body: dict,
    headers: dict,
    user_address: str
):
    """
    非流式代理转发

    Args:
        backend_url: 后端服务地址
        request_body: 请求体
        headers: 请求头
        user_address: 用户地址

    Returns:
        代理响应
    """
    async with httpx.AsyncClient(timeout=CLAUDE_REQUEST_TIMEOUT) as client:
        response = await client.post(
            backend_url,
            json=request_body,
            headers=headers
        )

        if response.status_code != 200:
            # 透传后端错误
            content_type = response.headers.get("content-type", "")
            if "application/json" in content_type:
                return JSONResponse(
                    status_code=response.status_code,
                    content=response.json()
                )
            else:
                return JSONResponse(
                    status_code=response.status_code,
                    content={"error": response.text}
                )

        result = response.json()

        # 记录真实 usage（可选）
        if "usage" in result:
            await _log_usage(user_address, result["usage"])

        return result


async def _stream_proxy(
    backend_url: str,
    request_body: dict,
    headers: dict,
    user_address: str
):
    """
    流式代理转发（SSE）

    Args:
        backend_url: 后端服务地址
        request_body: 请求体
        headers: 请求头
        user_address: 用户地址

    Returns:
        StreamingResponse
    """

    async def stream_generator():
        # 收集 usage 数据
        usage_data = {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0
        }

        try:
            async with httpx.AsyncClient(timeout=CLAUDE_REQUEST_TIMEOUT) as client:
                async with client.stream(
                    "POST",
                    backend_url,
                    json=request_body,
                    headers=headers
                ) as response:
                    # 检查响应状态
                    if response.status_code != 200:
                        error_text = await response.aread()
                        yield f"event: error\n"
                        yield f"data: {json.dumps({'error': error_text.decode()})}\n\n"
                        return

                    # 转发 SSE 事件
                    async for line in response.aiter_lines():
                        # 转发给客户端
                        yield f"{line}\n"

                        # 解析 usage 数据
                        parsed = parse_sse_usage(line)
                        if parsed:
                            if parsed["type"] == "start":
                                usage_data["input_tokens"] = parsed["input_tokens"]
                                usage_data["cache_creation_input_tokens"] = parsed["cache_creation_input_tokens"]
                                usage_data["cache_read_input_tokens"] = parsed["cache_read_input_tokens"]
                            elif parsed["type"] == "delta":
                                usage_data["output_tokens"] = parsed["output_tokens"]

        except Exception as e:
            yield f"event: error\n"
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

        finally:
            # 流结束后记录 usage
            if usage_data["input_tokens"] > 0 or usage_data["output_tokens"] > 0:
                await _log_usage(user_address, usage_data)

    return StreamingResponse(
        stream_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@app.post("/v1/messages")
async def claude_proxy(
    request: Request,
    claude_request: ClaudeMessageRequest,
    x_user_address: Optional[str] = Header(None)
):
    """
    Claude API 代理接口

    流程：
    1. 验证用户地址
    2. 检查并扣除余额
    3. 转发请求到后端代理
    4. 流式/非流式返回响应
    5. 记录真实 usage（可选）
    """
    # 1. 验证配置
    if not CLAUDE_BACKEND_URL or not CLAUDE_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="Claude backend not configured"
        )

    # 2. 验证用户地址（可选）
    user_address = None
    if x_user_address:
        try:
            user_address = Web3.to_checksum_address(x_user_address)
        except Exception:
            raise HTTPException(
                status_code=400,
                detail="Invalid user address"
            )
    elif DEFAULT_TEST_ADDRESS:
        # 使用默认测试地址
        user_address = Web3.to_checksum_address(DEFAULT_TEST_ADDRESS)
        print(f"⚠️  Using default test address: {user_address}")

    # 3. 检查并扣除余额（如果没有设置跳过余额检查且提供了用户地址）
    if not SKIP_BALANCE_CHECK and user_address:
        db = get_db()
        try:
            max_tokens = claude_request.max_tokens or MAX_TOKENS_PER_REQUEST
            success, error_msg, current_balance = await check_and_deduct_balance(
                user_address, max_tokens, db
            )

            if not success:
                estimated_mon = Decimal(max_tokens * 1.2) / Decimal(MON_TO_TOKEN_RATE)

                return JSONResponse(
                    status_code=402,
                    content={
                        "error": "payment_required",
                        "message": error_msg or "Insufficient MON balance",
                        "current_balance_mon": str(current_balance) if current_balance else "0",
                        "required_mon": str(estimated_mon)
                    }
                )
        finally:
            db.close()
    elif SKIP_BALANCE_CHECK:
        # 跳过余额检查（开发/测试模式）
        print("⚠️  SKIP_BALANCE_CHECK=true, skipping balance check")
    else:
        # 没有用户地址，跳过余额检查
        print("⚠️  No user address provided, skipping balance check")

    # 4. 准备代理请求
    proxy_headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {CLAUDE_API_KEY}",
        "anthropic-version": "2023-06-01",
    }

    # 透传客户端的特殊 header
    if "anthropic-beta" in request.headers:
        proxy_headers["anthropic-beta"] = request.headers["anthropic-beta"]

    request_body = claude_request.model_dump(exclude_none=True)

    # 5. 转发请求
    try:
        if claude_request.stream:
            # 流式响应
            return await _stream_proxy(
                CLAUDE_BACKEND_URL,
                request_body,
                proxy_headers,
                user_address
            )
        else:
            # 非流式响应
            return await _non_stream_proxy(
                CLAUDE_BACKEND_URL,
                request_body,
                proxy_headers,
                user_address
            )

    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Backend request timeout")
    except httpx.RequestError as e:
        raise HTTPException(status_code=503, detail=f"Backend service error: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

