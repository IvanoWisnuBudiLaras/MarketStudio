# Intelligence Studio — Technical Specification
Status PROPOSED. Mengikuti global TSD dan AGENTS; endpoint adalah candidate, bukan implementasi.

## Domain dan ownership
Entity kandidat: MetricSnapshot, InsightRun, ForecastRun, Recommendation. Setiap entity scoped workspace, memiliki opaque ID dan timestamp; mutable draft memakai version untuk optimistic concurrency. Authoritative data lintas studio diakses melalui service contract, bukan copy ledger. Jangan membuat database per studio. Validate membership, permission dan input di server. Financial quantity/cost mengikuti docs/platform/BUSINESS_RULES.md.

## API mapping
| Technical ID | Method/path relatif workspace | Entity | Requirement |
|---|---|---|---|
| TS-INT-01 | POST /metric-snapshots | MetricSnapshot | FR-INT-01 |
| TS-INT-02 | POST /insight-runs | InsightRun | FR-INT-02 |
| TS-INT-03 | POST /forecast-runs | ForecastRun | FR-INT-03 |
| TS-INT-04 | GET /recommendations | Recommendation | FR-INT-04 |

## Transaction dan state
Write request membawa idempotency key jika operasi berisiko duplicate; server membandingkan payload hash dan menolak mismatch. Atomic commit untuk perubahan domain terkait. Draft: draft → reviewed/approved → queued (bila eksternal) → processing → succeeded/failed/unknown; tidak semua entity memerlukan seluruh state. Approval terikat version dan target. External success hanya berdasarkan provider evidence; timeout dengan unknown outcome membutuhkan reconciliation. Read-only metric/simulation tidak mengubah source.

## Failure dan security
422 invalid input; 403 permission; 409 version/idempotency conflict; 503 dependency unavailable. Jangan leak tenant existence atau secret. Retry bounded hanya pada operasi aman. Audit menyimpan actor, workspace, operation, entity, version, request ID dan outcome; redact payload sensitif. Upload menggunakan allowlist dan size limit yang ditetapkan sebelum implementasi. Test cross-tenant, duplicate, rollback dan failure injection.

## Implementation order
Contract tests dan schema migration terlebih dahulu, service logic, API, UI states, integration tests, independent review. Jangan menambah library tanpa spike. Acceptance criteria adalah test design, bukan hasil test. Open: exact schema, limits, retention, dependency versions dan provider access. Atlas harus menyelesaikan open question yang memblokir ticket sebelum Forge coding.
