# EC2 application

Use Node.js 24. Run `npm ci` and `npm test` in this directory.

Copy root `.env.example` to private `.env`, supply the database values at runtime from Secrets Manager, and put the official RDS CA bundle at `certs/rds-ca.pem`. Never commit the private file or print credentials. RDS uses `PGSSLMODE=verify-full`; `disable` is only for isolated local database tests.

Before deployment, execute `schema.sql` on the intended database through an authorized private connection. Use a limited application user with SELECT/INSERT on messages and sequence usage. Schema initialization is explicit; the application does not require CREATE privileges.

From the repository root, run `docker compose up -d --build`. Only Nginx publishes port 80. The application image runs as the node user. Stop with `docker compose down`. No production database container is included.

Check `/`, `/time`, `/health`, and POST `/messages` with JSON `{ "text": "hello" }`. `/health` is process liveness, not database readiness. `/messages` performs a real parameterized insert and reads the inserted row back. It is an unauthenticated assessment demo, accepts at most 200 characters, and must not receive sensitive data. Database errors return a generic 503.

The browser polls server time every second and assigns it through textContent. No user data is reflected in HTML. Nginx applies security headers to error responses as well. HSTS is omitted until HTTPS exists. Image tags are versioned but not digest-pinned. AWS/RDS integration and browser execution need live verification before claiming deployment success.
