# Recursive tech trees

Tech trees that compose. A tech tree node can be a PR in a local project
or a reference to an entire tech tree managed elsewhere. This creates
a hierarchy where someone steering a large effort can see everything
in one graph, while individual projects remain autonomous.

Every tree is a pm repo with a target repo. There are no standalone
trees. The hierarchy comes from pm repos referencing other pm repos
as nodes in their tech tree. A lab's pm repo targets the lab's org
repo. A research project's pm repo targets its code repo. The lab's
tree has reference nodes pointing to the research project's pm repo.
This is just pm repos all the way down.

## Two modes

### Prescriptive (top-down)

A parent tree pushes structure down. A lab lead creates reference
nodes like "Auth system ready" and "Mobile app shipped" that link to
child pm repos. The child projects receive these as suggested plans
or constraints — they show up in the child's `pm plan list` as
external suggestions that can be accepted, adapted, or declined.

The parent tree tracks completion by pulling status from the children.
When a child project merges the PRs that satisfy a parent node, the
parent node transitions automatically.

This is the rigid hierarchy mode. The parent defines what needs to
happen and in what order. The children decide how.

Example:
```
lab-pm/ (targets lab-org-repo/)
├── node: "Auth system"          → links to auth-pm/ (targets auth-code/)
│   └── completion: all PRs in plan-001 merged
├── node: "Mobile app v1"        → links to mobile-pm/ (targets mobile-code/)
│   ├── depends-on: "Auth system"
│   └── completion: all PRs in plan-001 merged
└── node: "Public launch"
    └── depends-on: "Mobile app v1"
```

### Descriptive (bottom-up)

A parent tree observes without directing. Someone creates a pm repo
for their org and adds reference nodes that aggregate other projects
into a unified view. The child projects don't know they're being
observed and don't receive any suggestions. The parent pulls status
periodically and renders a read-only graph.

This is the aggregation mode. Nobody controls the children. The parent
is a lens for understanding what's happening across many independent
efforts.

Example: a researcher interested in mesh networking creates a pm repo
for their research group's org repo, and adds reference nodes that
track omerta_mesh, several independent VPN projects, and a few
protocol libraries. They define the dependency relationships they
see between these projects (even if the projects don't see them
themselves). The tree becomes a map of the space, anchored to an
org that cares about it.

## Data model

### Reference nodes in project.yaml

Reference nodes live alongside PR nodes in the existing `project.yaml`.
No new file type is needed — it's just a new node type in the existing
data model.

```yaml
# project.yaml — extended with reference nodes
project:
  target_repo: "/path/to/lab-org-repo"
  base_branch: main
  backend: vanilla

prs:
  - id: pr-001
    title: "Governance docs"
    status: in_progress
    # ... normal PR node

nodes:
  - id: node-001
    title: "Mesh networking layer"
    type: reference
    ref:
      pm_repo: "git@host:omerta-mesh-pm.git"
      match: plan-001           # track this plan's completion
    status: pending             # synced from child

  - id: node-002
    title: "pm mobile dashboard"
    type: reference
    ref:
      pm_repo: "/path/to/project-manager-pm"
      match: plan-001
    depends_on: [pr-001]        # can depend on local PRs
    status: pending

  - id: node-003
    title: "Public launch"
    type: milestone             # no ref, just a gate
    depends_on: [node-001, node-002]
    status: pending
```

### Node types

- **pr**: a normal PR node (existing behavior). Lives in `prs:`.
- **reference**: points to a child pm repo. Tracks a plan, a set
  of PRs, or the entire project. Status is synced from the child.
  Lives in `nodes:`.
- **milestone**: a gate with no backing work. Transitions when all
  dependencies are met. Lives in `nodes:`.

PRs and nodes share a dependency namespace — a milestone can depend
on a PR, a PR can depend on a reference node, etc. The graph is one
graph with different node types, not separate graphs stitched together.

### Link modes

Each reference node has a mode:

- **prescriptive**: the parent can push suggestions to the child.
  The child's pm instance shows these as external suggestions.
  Requires the child to opt in (add the parent as an `upstream`
  in their project.yaml).

- **descriptive**: read-only observation. The parent pulls status
  but never writes to the child. No opt-in required — works with
  any public pm repo.

```yaml
nodes:
  - id: node-001
    title: "Auth system"
    type: reference
    ref:
      pm_repo: "git@host:auth-pm.git"
      match: plan-001
      mode: prescriptive       # or "descriptive"
```

## Sync mechanics

### Pulling status (both modes)

`pm tree sync` clones or fetches each referenced pm repo, reads its
project.yaml, and updates node statuses. Same as `pm pr sync` but
across repos instead of across branches.

For descriptive mode, this is the only interaction. The parent reads,
never writes.

### Pushing suggestions (prescriptive only)

When a parent tree defines a node with prescriptive mode, it can
push a suggestion file to the child repo:

```yaml
# In the child pm repo: .pm-suggestions/from-<parent-id>.yaml
suggestion:
  from: "Lab roadmap"
  parent_repo: "git@host:lab-pm.git"
  nodes:
    - title: "Auth system must support OAuth2"
      context: "Required for mobile app integration"
      priority: high
```

The child sees these via `pm suggestions list` and can:
- `pm suggestions accept <id>` — creates a plan from the suggestion
- `pm suggestions decline <id>` — marks it declined, parent sees this
- Ignore it — it stays as a pending suggestion

The parent never force-creates plans or PRs in the child. It suggests.
The child decides.

## CLI extensions

```
# Tree management (reference nodes in any pm repo)
pm tree add <title>                   Add a reference or milestone node
pm tree link <node-id> <pm-repo>      Link a node to a child pm repo
pm tree sync                          Pull status from all children
pm tree graph                         Show the recursive graph
pm tree list                          List nodes with status

# Suggestions (prescriptive mode, in child projects)
pm suggestions list                   Show suggestions from parent trees
pm suggestions accept <id>            Create a plan from a suggestion
pm suggestions decline <id>           Decline a suggestion

# Existing commands, extended
pm pr graph --recursive               Expand reference nodes inline
pm pr ready --recursive               Show ready work across all children
```

## Composition

Trees compose recursively. A pm repo can have reference nodes pointing
to other pm repos, which themselves have reference nodes pointing to
further pm repos. There's no depth limit. At every level, the pm repo
targets a real repo (an org repo, a code repo, a docs repo — whatever
is appropriate for that level).

```
lab-pm/ (targets lab-org-repo/)
├── node: "Infrastructure"  → infra-pm/ (targets infra-org-repo/)
│   ├── node: "Mesh"        → omerta-mesh-pm/ (targets omerta-mesh/)
│   └── node: "PM tool"     → project-manager-pm/ (targets project-manager/)
├── node: "Products"        → products-pm/ (targets products-org-repo/)
│   ├── node: "Mobile app"  → mobile-pm/ (targets mobile-app/)
│   └── node: "Web app"     → web-pm/ (targets web-app/)
└── node: "Launch"
    └── depends-on: [Infrastructure, Products]
```

A person at the top sees the entire graph. A person working on the
mesh networking project sees only their local tree and any suggestions
pushed down to them.

## Access model

Follows the existing pm pattern: the pm repo is a git repo. Access
control is git access control. If you can clone the pm repo, you
can read its tree. If you can push to it, you can modify it.

Prescriptive mode requires the child to add the parent as an upstream,
which is a deliberate opt-in. No one can push suggestions to a project
that hasn't agreed to receive them.

Descriptive mode requires only read access to the child's pm repo
(or that the pm repo is public).

## Relationship to omerta_mesh

When omerta_mesh is available, tree sync becomes mesh-native. Instead
of cloning git repos over SSH/HTTPS, trees sync over the mesh. This
means:

- Private trees can link to private projects without either being
  publicly hosted
- Sync happens between devices on the mesh, no central server
- The descriptive mode becomes especially powerful: anyone on the
  mesh can aggregate any public project into their own tree, and
  "public" means "published to the mesh" not "hosted on a server
  someone else controls"

The prescriptive/descriptive split maps directly to the mesh's
trust model: prescriptive requires mutual trust (both sides opt in),
descriptive requires only that the child is visible on the mesh.

## Implementation order

This feature would itself be managed as a pm plan:

### Layer 0: Core data model
- Reference and milestone node types in project.yaml
- Mixed dependency graph (PRs and nodes share namespace)
- Tree sync: pull status from child pm repos

### Layer 1: Modes and visualization
- pm tree graph with recursive expansion (depends on: node types, sync)
- Descriptive mode: read-only aggregation (depends on: sync)
- Prescriptive mode: suggestion push/accept/decline (depends on: sync)

### Layer 2: Integration
- pm pr ready --recursive across trees (depends on: all layer 1)
- Dashboard: recursive tree view (depends on: graph)

### Layer 3: Mesh-native (after omerta_mesh)
- Mesh-native tree sync (depends on: layer 2, omerta_mesh)

## Open questions

- **Conflict resolution**: if a parent suggests a plan and the child
  modifies it significantly, how does the parent track completion?
  Probably: the parent defines a completion condition (e.g., "all PRs
  in plan-001 merged") and doesn't care about the specifics.

- **Staleness**: descriptive mode trees can go stale if children are
  offline or archived. Need a way to mark nodes as stale or dormant.

- **Identity**: how do trees reference each other across renames,
  moves, or re-hosts? Probably: by the repo_id (root commit hash),
  same as workdir naming.

- **Permissions granularity**: prescriptive mode is all-or-nothing
  (you accept the parent or you don't). Might want per-suggestion
  approval in the future, but start simple.
