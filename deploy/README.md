# Reproduce the SigNoz deployment with Foundry

This is the exact SigNoz deployment Agent Black Box was built and demoed against,
pinned so it can be reproduced.

- `casting.yaml` — the Foundry installation spec (self-hosted SigNoz via Docker Compose).
- `casting.yaml.lock` — the resolved, version-pinned lockfile Foundry generated.

## Run it

```bash
# 1. install foundryctl (once)
curl -fsSL https://signoz.io/foundry.sh | bash

# 2. from this folder, cast the pinned deployment
cd deploy
foundryctl cast -f casting.yaml
```

Foundry validates Docker, generates the Compose files into `pours/deployment/`,
and starts the stack. When it's up:

- SigNoz UI: http://localhost:8080 (first run creates a local admin account)
- OTLP ingest: `:4317` (gRPC) / `:4318` (HTTP)

Point the app at it with `OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318`
(already the default in `.env.example`), then run `python -m src.main demo`.

## Notes

- The only credentials in the lockfile are SigNoz's standard local-dev defaults
  (e.g. `POSTGRES_PASSWORD: signoz`); there are no real secrets.
- If the UI shows "No Data" after a Docker restart, SigNoz's replicated
  ClickHouse tables can come up read-only. Restore them with:
  `docker exec signoz-telemetrystore-clickhouse-0-0 clickhouse-client -q \
   "SYSTEM RESTORE REPLICA <db>.<table>"` for each table in
  `SELECT database, table FROM system.replicas WHERE is_readonly`.
