# Dashboard drill-down

Phase 88 (roadmap Milestone H, step 5). The bank is synthetic, and so are its executions.

**Drill-down** (in the navigation, and linked from the Overview's workflow panel) follows
workflow executions down four levels:

| Level | Shows | Broken down by |
| --- | --- | --- |
| Enterprise | Every execution | Country |
| Country | One country's executions | Department |
| Department | One department's executions in that country | Workflow |
| Workflow | One workflow's executions there | Step, and outcome |

At every level:
- **Figures:**
  - executions, completed, failed, in progress;
  - the failure rate: failed out of finished;
  - waiting approvals and human tasks (open tasks);
  - the average duration;
  - when the last execution started.
- **History:** live and simulated together, the live bank only, or simulations only.
- **Period:** all time, or the last 7, 30 or 365 days, by start time.
- **Breadcrumbs:** go back up a level. The page keeps its place in the URL, so a link
  opens the same view.

At the workflow level, each step shows its runs, failures, waiting work, and average and
95th-percentile duration, in the order the steps run. The outcomes are listed with their
counts.

## Where an execution belongs

Executions do not record a country or department. They are attributed when queried:

- **Country:** the first that applies:
  1. the execution's own input `country_code`;
  2. otherwise the workflow's catalogue country, when the catalogue gives exactly one (a
     country variant);
  3. otherwise none. These executions are grouped as **Not attributed**.
- **Department:** the workflow's catalogue department. Without one, the execution is
  grouped as **Unclassified**.
- **Workflow:** the execution's workflow id, labelled with its latest version's name.

The *Not attributed* and *Unclassified* groups can be opened like any other (`none` in the
API).

## Scopes

A user limited to countries or departments (Phase 84) sees only executions inside the
limit. **Executions without the attribute are left out too.** Elsewhere a record without
a country is not limited by a country scope. Here, counting unattributed executions would
give a scoped user bank-wide totals. The page says when a view is scoped.

This replaces, for the drill-down, the Phase 84 limitation "a scoped user's dashboards still
show bank-wide totals". The Overview's own figures are still bank-wide.

## API

`GET /api/v1/analytics/drilldown` requires `analytics:read`. Every person role holds it.

| Parameter | Values |
| --- | --- |
| `country` | An ISO code, or `none` |
| `department` | A department name, or `none`. Needs `country` |
| `workflow_id` | A workflow id. Needs `department` |
| `realm` | `all` (default), `live` or `simulation` |
| `days` | 1–3650, counted back from now by start time |

The response:
- `level`, and `path`: the breadcrumbs with their labels;
- `summary`: the figures for this place;
- `breakdown_by` and `breakdown`: one row per group, at most 500, largest first;
  `truncated` says when there were more;
- at the workflow level, `steps` and `outcomes` instead of a breakdown;
- `scope`, when the caller is scoped;
- `attribution`: the rules above, stated in the response.

## Measured

Each level was timed three times, and the median is shown. A scratch database held
1,000,000 synthetic live executions with 3,000,000 step runs, spread over 120 countries,
12 departments and 240 workflows.

| Level | Executions under it | Median |
| --- | --- | --- |
| Enterprise (120 countries) | 1,000,000 | 1.07 s |
| Country | 8,334 | 1.01 s |
| Department | 8,334 | 0.55 s |
| Workflow | 4,167 | 0.25 s |

On the development databases every level took under 0.65 s:
- `atlas_exit`: 36,686 executions;
- `atlas_gen`: 25,778 executions.

## Limitations

- **Attribution is computed per query.** The country comes from each execution's input, so
  the enterprise and country levels read every execution: about a second at a million. A
  stored attribution (a country and department column on the execution, filled when it
  starts) would allow an index; it is the next step if the history grows tenfold.
- **Only workflow executions are counted.** Payments, accounts and the other domain
  records have their own pages.
- **Durations of simulated executions are in simulated time.** Choose *Live bank* to see
  real time only.
- **No charts over time yet.** The figures are totals for the chosen period.
