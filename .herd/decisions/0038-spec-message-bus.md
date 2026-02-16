# HDR-0038 Spec: MCP Message Bus Implementation

## Data Model

```python
@dataclass
class Message:
    id: str                    # uuid
    from_addr: str             # mason.inst-a3f7b2c1@avalon
    to_addr: str               # wardenstein@avalon | @anyone@avalon | @everyone
    body: str                  # free text
    priority: str = "normal"   # normal | urgent
    sent_at: datetime = field(default_factory=datetime.utcnow)
    read_by: set[str] = field(default_factory=set)  # instance IDs that have read this
```

## In-Memory Store

```python
class MessageBus:
    """In-memory message bus. Lives inside the MCP server process."""

    def __init__(self) -> None:
        self._messages: list[Message] = []
        self._lock: asyncio.Lock = asyncio.Lock()
        self._stdin_handles: dict[str, IO] = {}  # instance_id -> stdin pipe

    async def send(self, from_addr: str, to_addr: str, body: str, priority: str = "normal") -> Message
    async def read(self, agent: str, instance: str, team: str) -> list[Message]
    def register_stdin(self, instance_id: str, handle: IO) -> None
    def unregister_stdin(self, instance_id: str) -> None
```

## Address Resolution

Parse `to_addr` into components:

```
agentName.instanceId@teamName
│         │           │
├─ agent  (optional — omit for @anyone/@everyone)
├─ instance (optional — omit for agent-level or broadcast)
└─ team    (optional — omit for cross-team)
```

Matching rules for `read()`:

| To address | Matches agent if... |
|---|---|
| `mason` | agent == "mason" |
| `mason@avalon` | agent == "mason" AND team == "avalon" |
| `mason.inst-abc@avalon` | instance == "inst-abc" |
| `@anyone` | agent not in ("rook", "vigil") AND first to read |
| `@anyone@avalon` | above AND team == "avalon" |
| `@everyone` | always |
| `@everyone@avalon` | team == "avalon" |

Leader visibility: if agent has `leader` role, also match `@*@{leader.team}` (all team-scoped traffic).

## MCP Tool: `herd_send`

```python
@mcp.tool()
async def herd_send(
    to: str,
    message: str,
    priority: str = "normal",
    agent_name: str | None = None,
) -> dict:
    """Send a message to an agent, team, or broadcast.

    Args:
        to: Recipient address (mason@avalon, @anyone, @everyone@leonardo, etc.)
        message: Message body.
        priority: "normal" or "urgent". Urgent triggers stdin injection for local agents.
        agent_name: Sender identity (auto-resolved from env if not provided).

    Returns:
        Dict with message_id and delivery status.
    """
```

## Piggyback Delivery

Wrapper applied to every tool response:

```python
async def _piggyback_messages(agent: str, instance: str, team: str, response: dict) -> dict:
    """Inject pending messages into any tool response."""
    pending = await bus.read(agent, instance, team)
    if pending:
        response["_pending_messages"] = [
            {"from": m.from_addr, "body": m.body, "priority": m.priority, "sent_at": str(m.sent_at)}
            for m in pending
        ]
    return response
```

Applied in every tool handler's return path, or as middleware on the FastMCP app.

## Stdin Injection (Urgent)

For `priority: urgent` messages to locally spawned agents:

```python
async def _inject_urgent(instance_id: str, message: Message) -> bool:
    """Write urgent message to agent's stdin pipe."""
    handle = self._stdin_handles.get(instance_id)
    if not handle:
        return False  # not local or handle lost — fall back to piggyback

    text = f"\n[URGENT from {message.from_addr}]: {message.body}\n"
    handle.write(text.encode())
    handle.flush()
    return True
```

Spawn tool registers the handle:

```python
# In spawn.py, after subprocess.Popen:
process = subprocess.Popen(cmd, stdin=subprocess.PIPE, ...)
bus.register_stdin(instance_code, process.stdin)
```

## Spawn Changes

Three additions to spawn:

1. **Populate `team`** on AgentRecord:
   ```python
   agent_record = AgentRecord(
       ...
       team=spawner_team,  # inherited from spawning agent's team
   )
   ```

2. **Retain stdin handle** (see above).

3. **Include instance ID in context payload:**
   ```
   ## YOUR INSTANCE
   Instance ID: {instance_code}
   Team: {team}
   Pass these on every MCP tool call.
   ```

## Message Lifecycle

1. `herd_send` called → message added to `_messages` list
2. If `priority: urgent` and recipient is local → stdin injection attempted
3. On any MCP tool call → `read()` checks for matching messages → piggybacked in response
4. `@anyone` messages: first agent to `read()` and match consumes it (removed from list)
5. `@everyone` messages: tracked via `read_by` set, removed when all active agents have read
6. Periodic cleanup: messages older than 1 hour pruned (prevent unbounded growth)

## Cross-Host

No special handling. Agent on Metropolis calls `herd_send` via HTTP to the MCP server on Avalon. Message enters the same in-memory store. Recipient picks it up on their next tool call, also via HTTP. The addressing scheme and HTTP transport make cross-host transparent.

Stdin injection only works for locally spawned agents (MCP server holds the pipe). Remote urgent messages fall back to piggyback delivery — still fast, just not instant.

## Files to Modify

| File | Change |
|---|---|
| `herd_mcp/bus.py` | **NEW** — MessageBus class, Message dataclass, address parser |
| `herd_mcp/server.py` | Add `herd_send` tool, piggyback middleware, MessageBus init |
| `herd_mcp/tools/spawn.py` | Retain stdin handle, populate team, include instance ID |
| `herd_core/types.py` | No change — `team` field already exists on Entity |
| `tests/test_bus.py` | **NEW** — addressing, routing, piggyback, lifecycle tests |
