-- Runs automatically via docker-entrypoint-initdb.d when postgres container first starts.
-- POSTGRES_DB=productsdb is already created by the image; we add ordersdb and paymentsdb.
-- Note: This runs as the POSTGRES_USER (novasurge), which is a superuser in postgres by default
-- when created via POSTGRES_USER env var. We stay in the default 'postgres' maintenance DB.

SELECT 'CREATE DATABASE ordersdb'
  WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'ordersdb')\gexec

SELECT 'CREATE DATABASE paymentsdb'
  WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'paymentsdb')\gexec

GRANT ALL PRIVILEGES ON DATABASE ordersdb TO novasurge;
GRANT ALL PRIVILEGES ON DATABASE paymentsdb TO novasurge;
