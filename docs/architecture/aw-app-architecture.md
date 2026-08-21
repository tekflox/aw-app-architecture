---
repo: architecture
path: docs/architecture/aw-app-architecture.md
source: generated
edited: false
checksum: sha256:01f2e1eef312c2c39c8e3150d591e7a5ce98166015761050312e41572aedfa69
---
# Architecture

- **repo**: aw-app-architecture
- **layer**: app
- **technologies**: python, react
- **health** (derived): planned

The Architecture namespace as a decoupled app: a structured catalog of components, BDD requirements, test traceability, bug history, technical debt, typed connections and exposed MCP tools — with health always DERIVED (a row can't claim "implemented" while a linked test fails or a bug is open). Merges the monolith's two disconnected surfaces (Settings > Architecture and Workspace > Tests) into one window, ships the ~41 MCP tools the catalog is managed through, and runs the test-discovery scan that keeps the traceability matrix populated without hand-registering every test file.

## Connections
- `db` → **postgres** — app-owned tables in the workspace schema
- `http` → **aw-workspace** — routes mounted at /api/apps/architecture
- `other` → **aw-app-tasks** — Provides the contributes
- `stdio-mcp` → **mcp-gateway** — MCP surface aggregated by the gateway

## MCP tools
- `create_component`
- `create_connection`
- `create_debt_note`
- `create_mcp_tool`
- `create_requirement`
- `create_testcase`
- `delete_component`
- `delete_connection`
- `delete_mcp_tool`
- `delete_requirement`
- `delete_testcase`
- `get_component`
- `get_component_connections`
- `get_component_requirements`
- `get_component_tools`
- `get_requirement_bug_history`
- `get_requirement_impact`
- `get_requirement_tests`
- `get_traceability_matrix`
- `link_requirement_kanban`
- `link_requirement_test`
- `list_components`
- `list_component_tests`
- `list_debt_notes`
- `list_flaky_testcases`
- `mark_testcase_flaky`
- `regenerate_architecture_docs`
- `report_bug`
- `resolve_bug`
- `resolve_debt_note`
- `run_component_tests`
- `run_test_discovery`
- `scan_workspace`
- `set_requirement_status`
- `set_testcase_run_command`
- `sync_component`
- `unlink_requirement_kanban`
- `unlink_requirement_test`
- `update_component`
- `update_requirement`
- `update_testcase_result`

## Requirements
### Toda tabela de um app carrega o prefixo app__<slug>__
- Given um app recebeu a capability db:own-tables
- When ele declara um modelo, uma FK, um índice ou uma VIEW
- Then o nome carrega o prefixo app__<slug>__, senão a facade recusa a criação no bootstrap — um único nome sem prefixo derruba o schema inteiro num log que ninguém lê
- intended_status: `not_implemented` · derived health: `not_implemented`
- tests: `repos/aw-app-architecture/tests/test_port_invariants.py` (passing)

### O scan nunca sobrescreve um componente curado
- Given um componente foi editado por uma pessoa ou por um agente (edited_by != 'scan')
- When o Workspace Scan roda de novo, agendado ou manual
- Then aquele componente é deixado intacto e contado como skipped_curated — sem essa regra um scan diário apaga toda descrição escrita, uma vez por tick
- intended_status: `not_implemented` · derived health: `not_implemented`
- tests: `repos/aw-app-architecture/tests/test_port_invariants.py` (passing)

### O scan converge numa única execução
- Given o catálogo está vazio e há apps que declaram dependência entre si
- When o Workspace Scan roda uma vez
- Then todas as arestas existem já na primeira passada — componentes são criados antes de qualquer conexão, porque create_connection resolve as duas pontas por slug e derruba silenciosamente a aresta que aponta pra frente
- intended_status: `not_implemented` · derived health: `not_implemented`
- tests: `repos/aw-app-architecture/tests/test_port_invariants.py` (passing)
