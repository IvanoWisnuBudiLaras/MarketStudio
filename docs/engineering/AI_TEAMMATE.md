# AI Teammate — tiga identitas, banyak skills
Status DIRECTION/PROPOSED. Orca-first, bukan membangun IDE baru. Tidak ada bukti runtime terhubung. MarketStudio adalah proving ground; tooling bukan fitur pelanggan UMKM.

## Roles
Atlas — Strategist: menerima ide, membaca konteks, riset, menyusun BRD/PRD/TSD, memecah ticket, memilih skill/harness, koordinasi. Tidak approve perubahan bisnis sendiri. Forge — Builder: full-stack, UX implementation, AI integration, database, tests dan deployment preparation. Tidak mengubah scope diam-diam atau merge sendiri. Nexus — Guardian & Enabler: independent review, security, skills, MCP, harness, memory dan workflow. Jika Nexus author tooling, Atlas atau reviewer independen memeriksa; jangan self-approve.

## Lifecycle
Task states: proposed → approved → assigned → in_progress → review → accepted → done. blocked dapat muncul dari assigned/in_progress/review; kembali setelah blocker resolved. rejected/cancelled terminal dengan alasan. Atlas membuat proposal; owner approve scope; Forge implement; Nexus review; owner approve merge/deploy sesuai policy. DONE membutuhkan acceptance evidence dan hasil review, bukan hanya status agent. Satu task memiliki owner, author, reviewer, branch/worktree, dependency, budget, acceptance, source refs dan evidence. Jangan menjalankan dependency yang belum accepted.

## Handoff envelope
Fields: task_id, from, to, objective, scope, non_scope, decision_refs, source_paths, acceptance_ids, branch, commit, changed_files, test_evidence, risks, blockers, requested_action. Jangan memasukkan secret atau full customer data. Receiver acknowledge dan memeriksa version/commit sebelum bekerja. Duplicate message tidak memicu duplicate task. Manual Markdown handoff adalah fallback yang sah.

## Runtime dan memory
Identitas independen dari model. Preferred Atlas Codex, Forge Gemini, Nexus Codex/flexible. Exact model ID dan reasoning effort OPEN; periksa installed harness dan entitlement. Tidak mengunci nama Astra/Sol/Gemini 3.8 tanpa verifikasi. Maksimal 2–3 active sessions awal sebagai usulan; budget dan concurrency configurable. Git/Markdown menjadi durable knowledge; SQLite hanya jika task state membutuhkan transaksi. Session recovery membaca task, commit, last evidence dan unresolved blockers; jangan mengulang side effect. Memory menyimpan keputusan, source, confidence, date dan scope; tidak menyimpan credential. Owner dapat mengoreksi memory; status keputusan hanya berubah dengan approval.

## Evaluation
Uji satu ticket dari proposal sampai review. Ukur handoff completeness, acceptance pass, rework, token/cost jika tersedia, dan human intervention. Uji missing dependency, duplicate task, agent crash, conflicting edits, malicious tool output, revoked permission. Tidak ada self-modifying policy otomatis. Skill improvement diajukan sebagai diff, diuji dan direview sebelum dipakai. Jangan mengklaim Orca native support sebelum inspect dokumentasi/instalasi aktual.
