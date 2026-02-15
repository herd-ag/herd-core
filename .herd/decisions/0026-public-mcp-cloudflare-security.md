---
status: accepted
date: 2026-02-15
decision-maker: Faust
principle: Defense in depth — four layers, zero open ports
scope: architecture
superseded-by: null
---

# HDR-0026: Public MCP Access via Cloudflare Tunnel

**Status:** Accepted
**Date:** 2026-02-15
**Participants:** Faust (Architect), Claude (Advisor)
**Context:** Securing Metropolis MCP endpoint for remote access without exposing home network

## Decision

Expose the Herd MCP server through Cloudflare Tunnel with layered Zero Trust security. No open ports. No exposed IP. No self-managed certificates.

### Four Security Layers

**Layer 1 — Cloudflare Tunnel (network)**
The `cloudflared` daemon on Metropolis makes an outbound-only connection to Cloudflare's edge network. No ports opened on router. No firewall rules. No static IP required. Home IP never exposed. This alone eliminates 90% of attack surface.

**Layer 2 — Cloudflare Access / Zero Trust (identity)**
Before any request reaches MCP, Cloudflare authenticates the caller. Free for up to 50 users.

For humans: GitHub OAuth or email one-time PIN, 24-hour sessions.
For machines: Service tokens with CF-Access-Client-Id/Secret headers.

**Layer 3 — MCP application auth (defense in depth)**
Even if someone bypasses Cloudflare (misconfiguration, compromised token), the MCP server itself validates a Herd API key on every request. Belt and suspenders.

**Layer 4 — Read/write authorization (application logic)**
MCP endpoints enforce operation-level permissions:
- architect: read all, write all, admin true
- team_leader: read all, write [log, transition, assign, spawn]
- observer: read [status, metrics, catchup], write none

### Single MCP Endpoint

One MCP server on Metropolis. All teams and all clients connect to the same endpoint. No split-brain. No sync. One auth surface. One audit log.

### Metropolis Container Stack

```yaml
# docker-compose.yml on Metropolis
services:
  herd-mcp:
    container_name: herd-mcp
    image: herd-mcp:latest
    ports:
      - "127.0.0.1:8080:8080"   # localhost only
    volumes:
      - ./data/duckdb:/data/duckdb
      - ./data/lancedb:/data/lancedb
      - ./.herd:/herd
    env_file:
      - .env
    restart: unless-stopped

  cloudflared:
    container_name: cloudflared
    image: cloudflare/cloudflared:latest
    command: tunnel run
    environment:
      - TUNNEL_TOKEN=${CF_TUNNEL_TOKEN}
    restart: unless-stopped
    depends_on:
      - herd-mcp
```

Two containers. MCP server binds to localhost only — unreachable from network directly. Cloudflared tunnel is the only path in. No nginx, no certbot, no port forwarding.

## Rationale

### Why Cloudflare Tunnel
- Outbound-only connection — no open ports on home network
- Home IP never exposed — cannot be targeted
- Free tier covers all needs — tunnel, Access, DNS, DDoS, WAF
- Automatic TLS — no certificate management
- Works behind CGNAT — no ISP dependency
- Trivial setup — one Docker container with a token

### Why Not Alternatives
- **Port forwarding + nginx + certbot:** Exposes home IP, requires static IP or dynamic DNS, manual cert renewal. Sysadmin work the audience shouldn't need.
- **VPN (WireGuard/Tailscale):** Good for personal access but doesn't scale to OSS community.
- **Cloud VM:** Adds monthly cost and latency. Defeats the purpose of self-hosting.

### Why Four Layers
Defense in depth. Each layer addresses a different failure mode. Any single layer could be compromised without breaching the system. All four would need to fail simultaneously.

### Cost
Zero. Cloudflare free tier includes: unlimited tunnels, Access for up to 50 users, DNS management, DDoS protection, basic WAF rules, access audit logs.

## Implementation Required

1. Register domain on Cloudflare (or transfer existing)
2. Create Cloudflare Tunnel via dashboard
3. Deploy `cloudflared` container on Metropolis
4. Configure Cloudflare Access application with OAuth
5. Issue service token for Avalon
6. Implement API key validation in MCP server
7. Implement permission-level authorization in MCP
8. Containerize MCP server (Docker)
9. `herd deploy` CLI command to automate tunnel setup

## Consequences

- Metropolis is publicly accessible at `herd.yourdomain.com` without any open ports
- All traffic encrypted end-to-end via Cloudflare TLS
- Human access via OAuth — check Herd status from phone anywhere
- Machine access via service tokens — Avalon connects from any network
- Audit trail of every access attempt in Cloudflare logs
- No sysadmin knowledge required beyond `docker compose up`
- ISP changes, router resets, CGNAT — none affect accessibility
