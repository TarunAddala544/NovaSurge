-- Runs automatically via docker-entrypoint-initdb.d when postgres container first starts.
-- POSTGRES_DB=productsdb is already created by the image; we add the other two.

\c postgres

CREATE DATABASE ordersdb;
GRANT ALL PRIVILEGES ON DATABASE ordersdb TO novasurge;

CREATE DATABASE paymentsdb;
GRANT ALL PRIVILEGES ON DATABASE paymentsdb TO novasurge;
