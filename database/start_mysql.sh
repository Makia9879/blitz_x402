#!/usr/bin/env bash
set -e

CONTAINER_NAME="blitz-mysql"
MYSQL_ROOT_PASSWORD="root"
MYSQL_DB="blitz_x402"
MYSQL_USER="blitz"
MYSQL_PASSWORD="blitz_pwd"

echo "Starting MySQL docker container: ${CONTAINER_NAME}"

# 如果已存在同名容器，先删除
if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
  echo "Container ${CONTAINER_NAME} already exists, removing..."
  docker rm -f "${CONTAINER_NAME}"
fi

# 启动 MySQL 容器
docker run -d \
  --name "${CONTAINER_NAME}" \
  -p 3306:3306 \
  -e MYSQL_ROOT_PASSWORD="${MYSQL_ROOT_PASSWORD}" \
  -e MYSQL_DATABASE="${MYSQL_DB}" \
  -e MYSQL_USER="${MYSQL_USER}" \
  -e MYSQL_PASSWORD="${MYSQL_PASSWORD}" \
  mysql:8.0

echo "Waiting MySQL to be ready..."
# 简单等待几秒，也可以改成更严格的健康检查
sleep 15

echo "Creating tables in database ${MYSQL_DB}..."

docker exec -i "${CONTAINER_NAME}" mysql -u"${MYSQL_USER}" -p"${MYSQL_PASSWORD}" "${MYSQL_DB}" << 'SQL'
CREATE TABLE IF NOT EXISTS user_balances (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  user_address VARCHAR(42) NOT NULL UNIQUE,
  balance DECIMAL(36, 0) NOT NULL DEFAULT 0, -- 单位：wei
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS recharge_records (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  user_address VARCHAR(42) NOT NULL,
  amount DECIMAL(36, 0) NOT NULL,      -- 单位：wei
  tx_hash VARCHAR(66) NOT NULL,
  client_type VARCHAR(16) NOT NULL,    -- "mcp" / "web" / "x402-gateway" 等
  status VARCHAR(16) NOT NULL,         -- "pending" / "success" / "failed"
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uniq_user_tx (user_address, tx_hash)
);
SQL

echo "MySQL is up and tables are created."
echo "Connection DSN for Python: mysql+pymysql://${MYSQL_USER}:${MYSQL_PASSWORD}@localhost:3306/${MYSQL_DB}"
