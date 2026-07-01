# QA-07 Audit Index

**Generated:** 2026-07-02  
**Source evidence:** `TF3---Self-Heal/evidence/qa-07/offline_scenario_run_14.txt`

| scenario_id | tenant_id | correlation_id | outcome | action / decision | evidence path |
|---|---|---|---|---|---|
| sc01 | tenant-a | `sc01-0000-0000-0000-000000000000` | auto_resolved | PATCH_MEMORY_LIMIT | `evidence/qa-07/offline_scenario_run_14.txt` |
| sc02 | tenant-a | `sc02-0000-0000-0000-000000000000` | auto_resolved | RESTART_DEPLOYMENT | `evidence/qa-07/offline_scenario_run_14.txt` |
| sc03 | tenant-a | `sc03-0000-0000-0000-000000000000` | auto_resolved | RESTART_DEPLOYMENT | `evidence/qa-07/offline_scenario_run_14.txt` |
| sc04 | tenant-a | `sc04-0000-0000-0000-000000000000` | auto_resolved | ROLLOUT_UNDO | `evidence/qa-07/offline_scenario_run_14.txt` |
| sc05 | tenant-a | `sc05-0000-0000-0000-000000000000` | auto_resolved | PATCH_MEMORY_LIMIT | `evidence/qa-07/offline_scenario_run_14.txt` |
| sc06 | tenant-b | `sc06-0000-0000-0000-000000000000` | auto_resolved | PATCH_MEMORY_LIMIT | `evidence/qa-07/offline_scenario_run_14.txt` |
| sc07 | tenant-b | `sc07-0000-0000-0000-000000000000` | auto_resolved | RESTART_DEPLOYMENT | `evidence/qa-07/offline_scenario_run_14.txt` |
| sc08 | tenant-b | `sc08-0000-0000-0000-000000000000` | auto_resolved | RESTART_DEPLOYMENT | `evidence/qa-07/offline_scenario_run_14.txt` |
| sc09 | tenant-a | `sc09-0000-0000-0000-000000000000` | rolled_back | verify returned ROLLBACK | `evidence/qa-07/offline_scenario_run_14.txt` |
| sc10 | tenant-a | `sc10-0000-0000-0000-000000000000` | auto_resolved | SCALE_REPLICAS deferred path | `evidence/qa-07/offline_scenario_run_14.txt` |
| sc11 | tenant-a | `sc11-0000-0000-0000-000000000000` | escalated:denied_cross_tenant | safety denied target namespace tenant-b | `evidence/qa-07/offline_scenario_run_14.txt` |
| sc12 | tenant-a | `sc12-0000-0000-0000-000000000000` | escalated:denied_action_not_allowed | safety denied DELETE_NAMESPACE | `evidence/qa-07/offline_scenario_run_14.txt` |
| sc13 | tenant-a | `sc13-0000-0000-0000-000000000000` | low_confidence_no_action | pre-decide stopped action | `evidence/qa-07/offline_scenario_run_14.txt` |
| sc14 | tenant-a | `sc14-0000-0000-0000-000000000000` | escalated:verify_escalate | verify returned ESCALATE bundle | `evidence/qa-07/offline_scenario_run_14.txt` |

Summary from runner:

```text
Rounds run         : 1
Incidents injected : 14
Auto-resolved      : 10/14 = 71.4%  (target >=60%)
Match expected     : 14/14
RESULT: PASS
```
