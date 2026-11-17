#!/bin/sh
# Creates the least-privilege MySQL accounts Office-Mates uses (BLUEPRINT section 8.2).
#
#   app_rw        the API and workers: read/write data, no schema changes
#   migrator      Alembic only: may change the schema
#   readonly_ops  humans/ops tools: read only
#
# Runs automatically the first time the MySQL volume is created. It is idempotent, so it
# can also be re-run at any time (e.g. after changing a password in .env):
#   docker compose exec mysql sh /docker-entrypoint-initdb.d/10-users.sh
set -eu

: "${MYSQL_ROOT_PASSWORD:?}" "${MYSQL_APP_PASSWORD:?}" "${MYSQL_MIGRATOR_PASSWORD:?}" "${MYSQL_READONLY_PASSWORD:?}"

# Inside the MySQL container the client uses the local socket. CI runs this script from
# the runner instead and sets MYSQL_HOST / MYSQL_PORT to reach the service container.
set --
if [ -n "${MYSQL_HOST:-}" ]; then
  set -- --protocol=TCP -h "$MYSQL_HOST" -P "${MYSQL_PORT:-3306}"
fi

# The password is passed through the environment, not the command line, so it never
# appears in the process list.
MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot "$@" <<SQL
CREATE DATABASE IF NOT EXISTS officemates      CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
CREATE DATABASE IF NOT EXISTS officemates_test CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;

CREATE USER IF NOT EXISTS 'app_rw'@'%'       IDENTIFIED BY '${MYSQL_APP_PASSWORD}';
CREATE USER IF NOT EXISTS 'migrator'@'%'     IDENTIFIED BY '${MYSQL_MIGRATOR_PASSWORD}';
CREATE USER IF NOT EXISTS 'readonly_ops'@'%' IDENTIFIED BY '${MYSQL_READONLY_PASSWORD}';
ALTER USER 'app_rw'@'%'       IDENTIFIED BY '${MYSQL_APP_PASSWORD}';
ALTER USER 'migrator'@'%'     IDENTIFIED BY '${MYSQL_MIGRATOR_PASSWORD}';
ALTER USER 'readonly_ops'@'%' IDENTIFIED BY '${MYSQL_READONLY_PASSWORD}';

-- Start from nothing so re-running never leaves stale privileges behind.
REVOKE ALL PRIVILEGES, GRANT OPTION FROM 'app_rw'@'%', 'migrator'@'%', 'readonly_ops'@'%';

GRANT SELECT, INSERT, UPDATE, DELETE ON officemates.*      TO 'app_rw'@'%';
GRANT SELECT, INSERT, UPDATE, DELETE ON officemates_test.* TO 'app_rw'@'%';

GRANT ALL PRIVILEGES ON officemates.*      TO 'migrator'@'%';
GRANT ALL PRIVILEGES ON officemates_test.* TO 'migrator'@'%';

GRANT SELECT ON officemates.* TO 'readonly_ops'@'%';

FLUSH PRIVILEGES;
SQL

echo "office-mates: database users configured"
