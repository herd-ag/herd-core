# Herd Dashboard Reference

The Herd dashboards are built with Evidence.dev and provide operational visibility into agent performance, costs, quality, and delivery. All dashboards query the `herd_dm` schema (gold layer mart models).

## Running Locally

```bash
cd .herd/evidence
npm install
npm run dev
```

This starts a local development server (default: `http://localhost:3000`). Dashboards auto-reload on file changes.

**Prerequisite**: The dbt gold layer must be built first so that `herd_dm` dimension and fact tables are populated.

---

## Dashboard Pages

### 1. Executive Overview (`index.md`)

**Questions answered**: What is the current state of the system? How are costs trending? What work was delivered recently?

**Key metrics**:
- Active agents (vs total)
- Open tickets
- PRs merged this week
- Total cost (USD)
- Cost per line of code

**Charts**:
- Agent utilization table (code, role, status, instances, tokens, cost)
- Daily and cumulative cost trend (30 days) -- line chart
- Agents by status -- bar chart

**Data table**: Recent pull requests (last 7 days) with PR code, title, ticket, agent, merge date, lines, files.

**Source tables**: `dim_agent`, `dim_ticket`, `dim_date`, `dim_pull_request`, `fact_agent_instance_cost`, `fact_agent_instance_work`, `fact_pr_delivery`

---

### 2. Agent Performance (`agents.md`)

**Questions answered**: Which agents deliver the most value? Who produces clean code? What are the cost differences between models?

**Key metrics**:
- Sessions, tickets worked, total tokens, total cost per agent
- First-pass QA rate per agent
- Cost per line of code per agent
- Model cost comparison per agent

**Charts**:
- First-pass QA rate by agent -- bar chart
- Cost per line vs total lines -- scatter plot
- Cost by agent and model (stacked) -- bar chart
- Session count by agent -- bar chart

**Data tables**:
- Agent summary (sessions, success rate, tickets, tokens, cost, avg duration)
- QA pass rates (reviews, first-pass count, approval rate, avg findings)
- Cost efficiency (PRs, lines, cost, cost/line by model)
- Model usage (sessions, tokens, cost, avg cost/session by provider)
- Craft assignments per agent
- Work distribution (lifecycle events, ticket activities, PR activities)

**Source tables**: `dim_agent`, `dim_craft`, `dim_model`, `dim_ticket`, `fact_agent_instance_cost`, `fact_agent_instance_work`, `fact_pr_delivery`, `fact_review_quality`

---

### 3. Token Economics (`costs.md`)

**Questions answered**: What is the total cost? How are costs trending? Which models consume the most budget? How effective is caching?

**Key metrics**:
- Total cost, cost per ticket, cost per session
- Average daily cost, projected monthly and annual costs
- Cache utilization ratio

**Charts**:
- Daily and cumulative costs (60 days) -- line chart
- Total cost by model -- bar chart
- Cache utilization trend (30 days) -- line chart
- Cost per line trend (30 days) -- line chart

**Data tables**:
- Cost by model (sessions, input/output/cache tokens, total cost, avg/session)
- Most expensive tickets (top 20 by total cost)

**Source tables**: `dim_date`, `dim_model`, `dim_ticket`, `fact_agent_instance_cost`, `fact_agent_instance_work`, `fact_pr_delivery`

---

### 4. Sprint Tracking (`sprint.md`)

**Questions answered**: What is the sprint status? Are we on pace? Which agents contributed most? How does velocity compare historically?

**Key metrics**:
- Completed, in-progress, and to-do ticket counts
- Active sprint indicator

**Interactive controls**: Sprint dropdown selector for analyzing any recent sprint (last 90 days).

**Charts**:
- Sprint burndown (remaining vs completed tickets) -- line chart
- PRs merged by agent -- bar chart
- Sprint velocity (tickets completed, last 6 sprints) -- bar chart

**Data tables**:
- Sprint tickets detail (code, title, status, size, assignee)
- Agent contributions (PRs, lines changed, cost)
- Recent activity (last 20 events with timestamps)

**Source tables**: `dim_agent`, `dim_date`, `dim_sprint`, `dim_ticket`, `fact_agent_instance_cost`, `fact_pr_delivery`, `fact_sprint_burndown`

---

### 5. QA Analytics (`qa.md`)

**Questions answered**: How effective is QA? What types of issues are most common? What is the cost of rework?

**Key metrics**:
- Total reviews, first-pass rate, total findings, average review time
- Blocking vs advisory finding distribution
- Rework cost as percentage of total cost

**Charts**:
- First-pass QA rate trend (30 days) -- line chart
- Reviews by finding category -- bar chart
- Findings by agent (blocking vs advisory) -- bar chart
- Reviews by round -- histogram
- Review duration distribution -- histogram

**Data tables**:
- Findings by agent (total, blocking, advisory, avg per review)
- Review rounds (count, approved, approval rate per round)
- Rework cost analysis (top 20 tickets by rework cost)

**Source tables**: `dim_agent`, `dim_date`, `dim_ticket`, `dim_pull_request`, `fact_agent_instance_cost`, `fact_review_quality`

---

### 6. Efficiency Metrics (`efficiency.md`)

**Questions answered**: How productive are sessions? Which agents accomplish the most per session? Is efficiency improving?

**Key metrics**:
- Total sessions, average session duration, events per session, activities per session
- Context window utilization percentage
- Cache hit rate by agent
- Cost per activity unit

**Charts**:
- Average activity per session by agent -- bar chart
- Context window utilization by agent -- bar chart
- Cache hit rate by agent -- bar chart
- Session duration distribution -- bar chart
- Cost per activity vs total activities -- scatter plot
- Efficiency trend (activities per hour, 30 days) -- line chart

**Data tables**:
- Session productivity (duration, lifecycle/ticket/PR activities per agent)
- Context utilization (model, window size, avg tokens, utilization %)
- Cache hit rate (direct tokens, cache read/create, hit rate %)
- Token efficiency (sessions, activities, cost, cost/activity)
- Compaction opportunities (long sessions with low activity)
- Activity type distribution (lifecycle, ticket, PR totals and averages)

**Source tables**: `dim_agent`, `dim_date`, `dim_model`, `fact_agent_instance_cost`, `fact_agent_instance_work`

---

### 7. Pipeline Overview (`pipeline.md`)

**Questions answered**: What is the work-in-progress state? Where are the bottlenecks? Which tickets are blocked?

**Key metrics**:
- Active, backlog, in-progress, in-review, and blocked ticket counts

**Charts**:
- Average time in status -- bar chart
- Ticket flow (created, started, completed per day, 30 days) -- line chart
- Average cycle time by ticket size -- bar chart

**Data tables**:
- Time in status (avg, median, min, max minutes per status)
- Handoff latency (transition pairs with avg/median hours)
- Blocked tickets (ticket, blocker, agent, blocked since)
- Cycle time by size (XS through XL with avg/median hours)
- Longest in-progress tickets (top 20 by hours)

**Source tables**: `dim_agent`, `dim_date`, `dim_ticket`, `fact_ticket_lifecycle`, `fact_pr_delivery`

---

### 8. Architect View (`architect.md`)

**Questions answered**: How much coordination overhead does the coordinator (Steve) require? Is agent autonomy increasing?

**Key metrics**:
- Total coordinator sessions, tickets coordinated, lifecycle events, total cost
- Autonomy ratio (percentage of sessions without architect involvement)

**Charts**:
- Architect activity trend (sessions and events, 30 days) -- line chart
- Coordination cost by ticket size -- bar chart
- Sessions by intervention type -- bar chart
- Session duration distribution -- histogram

**Data tables**:
- Tickets requiring intervention (top 20 by session count)
- Coordination cost by ticket size (XS through XL)
- Intervention types (lifecycle, ticket coordination, PR management)
- Recent coordination activity (last 50 sessions)

**Source tables**: `dim_agent`, `dim_date`, `dim_ticket`, `dim_model`, `fact_agent_instance_cost`, `fact_agent_instance_work`

---

### 9. Prompt Analytics (`prompts.md`)

**Questions answered**: How successful are agent sessions? Do smaller tickets succeed more often? Does initial success predict QA outcomes?

**Key metrics**:
- Total sessions, successful sessions, success rate, total cost

**Charts**:
- Success rate by ticket size -- bar chart
- Success rate by agent role -- bar chart
- Sessions by outcome -- bar chart
- First-pass QA rate by initial prompt quality -- bar chart
- Success rate trend (30 days) -- line chart

**Data tables**:
- Success by ticket size (sessions, successes, rate)
- Success by agent role (sessions, successes, rate, cost)
- Session outcomes (count, cost, avg duration per outcome)
- Craft impact on success (craft code, description, sessions, rate)
- QA-prompt correlation (prompt quality vs first-pass QA rate)
- Model performance by outcome (sessions, successes, rate, cost)

**Source tables**: `dim_agent`, `dim_craft`, `dim_date`, `dim_model`, `dim_ticket`, `dim_pull_request`, `fact_agent_instance_cost`, `fact_agent_instance_work`, `fact_review_quality`

---

### 10. Ticket Detail (`ticket/[ticket_code].md`)

**Dynamic route**: Access via `/ticket/DBC-87` (any valid ticket code).

**Questions answered**: What is the full history of this ticket? What resources were consumed? How did it progress through the workflow?

**Key metrics**:
- Status, size, sprint, project
- Sessions, agents involved, total cost
- PRs created, reviews conducted, total lines changed

**Charts**:
- Cost by agent -- bar chart
- Time spent in each status -- bar chart

**Data tables**:
- Ticket lifecycle (event timeline with status transitions, agents, durations, blockers)
- Agent sessions (instance code, start/end times, duration, outcome, model, tokens, cost)
- Review history (reviewer, round, verdict, finding counts, duration)
- Cost breakdown by agent and model (input/output/cache tokens, cost)
- Pull requests (PR code, title, author, branch, merge date, lines, files)
- Time distribution (minutes per status)

**Source tables**: `dim_agent`, `dim_model`, `dim_pull_request`, `dim_ticket`, `fact_agent_instance_cost`, `fact_agent_instance_work`, `fact_pr_delivery`, `fact_review_quality`, `fact_ticket_lifecycle`
