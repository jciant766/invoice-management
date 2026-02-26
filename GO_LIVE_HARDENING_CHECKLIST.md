# Go-Live Hardening Checklist

Purpose: operational and security sign-off checklist before full council migration.

Scope:
- Invoice records in `invoice_management.db`
- Receipt files in `uploads/fiscal_receipts/`
- Backup, restore, and evidence-chain controls

Process model confirmed:
- `Approved` = approved to pay
- Receipt may arrive after approval
- Invoice cannot be treated as fully closed/reconciled without receipt

Last updated: 2026-02-26

---

## How to use this document

For each control:
- mark `PASS` or `FAIL`
- record evidence
- assign owner and due date if failed

Severity legend:
- `Critical`: must pass before go-live
- `High`: should pass before go-live, otherwise formal risk acceptance required
- `Medium`: can be staged, but must have dated plan

---

## A. Data Integrity and Receipt Reliability

### A1. Atomic receipt replace
- Severity: `Critical`
- Risk if missing: replacing a receipt can leave invoice with no valid receipt if failure happens mid-write.
- Pass criteria:
1. Replace flow writes new file first.
2. Database pointer is updated only after new file write succeeds.
3. Old file is deleted only after DB update succeeds.
4. Failure during replace keeps old receipt usable.
- Evidence:
1. Code path documented.
2. Test proving simulated write/update failure does not lose existing receipt.
- Status: `FAIL` (current code deletes old file before final swap)
- Owner:
- Target date:

### A2. Receipt presence rule aligned to workflow
- Severity: `High`
- Risk if missing: invoices can stay open indefinitely without documentary proof.
- Pass criteria:
1. `Approved to pay` is allowed without receipt.
2. `Closed/Reconciled` state requires receipt attached.
3. UI clearly shows missing-receipt queue.
- Evidence:
1. Workflow/state definition in docs.
2. UI screenshot showing missing-receipt indicator/filter.
3. Test proving close/reconcile is blocked when receipt is absent.
- Status: `FAIL` (state exists for approval, but no enforced close/reconcile gate)
- Owner:
- Target date:

### A3. Nightly receipt integrity scan
- Severity: `High`
- Risk if missing: missing files and silent drift discovered only during audit.
- Pass criteria:
1. Nightly job checks all invoices with `fiscal_receipt_path`.
2. Reports missing linked files.
3. Reports orphan files not linked to invoices.
4. Reports checksum mismatch vs stored baseline (if hashing enabled).
- Evidence:
1. Scheduled job definition (cron/systemd timer).
2. Last 7 daily reports.
3. Alert path documented (who receives failures).
- Status: `FAIL` (no automated nightly scan)
- Owner:
- Target date:

---

## B. Backup, Restore, and Disaster Recovery

### B1. Consistent backup unit (DB + receipts together)
- Severity: `Critical`
- Risk if missing: restored DB references receipt files that do not exist.
- Pass criteria:
1. Backup captures DB and `uploads/fiscal_receipts/` in the same snapshot.
2. Backup artifact is timestamped as one recovery set.
3. Restore restores both DB and receipt files together.
- Evidence:
1. Backup script/command for combined set.
2. Sample artifact list showing both DB and receipts.
3. Restore runbook with combined restore steps.
- Status: `FAIL` (current backups are DB-only)
- Owner:
- Target date:

### B2. Off-site backup copy
- Severity: `Critical`
- Risk if missing: local server loss/ransomware can remove both live data and local backups.
- Pass criteria:
1. Daily replication of backup sets to separate location/account.
2. Off-site retention policy defined (for example 30/90/365 days).
3. Access control and credentials documented.
- Evidence:
1. Destination path/storage proof.
2. Replication logs for last 14 days.
3. Retention policy document.
- Status: `FAIL` (DB external path exists, receipt backup off-site not established)
- Owner:
- Target date:

### B3. Monthly restore drill
- Severity: `High`
- Risk if missing: backups may exist but be unusable when needed.
- Pass criteria:
1. Monthly restore to non-production environment.
2. Validation checks:
   - app starts
   - invoice counts match expected
   - sample receipts open correctly
3. Recovery time and issues logged.
- Evidence:
1. Restore drill logs for last 3 months.
2. Signed checklist per drill.
- Status: `FAIL` (no documented recurring drill)
- Owner:
- Target date:

---

## C. Access Control and Auditability

### C1. Receipt action permissions
- Severity: `High`
- Risk if missing: any authenticated user may replace/delete receipts beyond role responsibility.
- Pass criteria:
1. Role policy defines who can upload/replace/delete receipts.
2. Endpoints enforce role checks.
3. Unauthorized attempts are denied and logged.
- Evidence:
1. Permission matrix.
2. Test cases for allow/deny by role.
- Status: `FAIL` (authenticated check exists; fine-grained role control not explicit)
- Owner:
- Target date:

### C2. Receipt upload/replace/delete audit trail
- Severity: `High`
- Risk if missing: weak evidence chain during disputes or audits.
- Pass criteria:
1. Audit event logged for upload, replace, delete.
2. Log includes user, invoice id, timestamp, source IP, action result.
3. Audit view can filter receipt actions.
- Evidence:
1. Sample audit log entries.
2. Query/export showing receipt action history.
- Status: `FAIL` (invoice status actions logged; receipt file actions not explicit)
- Owner:
- Target date:

---

## D. Security and Storage Hardening

### D1. Receipt storage protection at rest
- Severity: `Medium`
- Risk if missing: direct disk access exposes receipt content.
- Pass criteria (choose at least one):
1. Disk/volume encryption enabled on server, or
2. Application-level encryption for receipt files.
- Evidence:
1. Infrastructure config or encryption design note.
2. Recovery key handling documented.
- Status: `FAIL` (no explicit receipt-file encryption control documented)
- Owner:
- Target date:

### D2. Retention and legal hold policy
- Severity: `Medium`
- Risk if missing: receipts kept too short (compliance risk) or too long (privacy risk).
- Pass criteria:
1. Policy defines retention period by record type.
2. Deletion/hold exceptions process documented.
3. System behavior aligned with policy.
- Evidence:
1. Approved retention policy.
2. Admin procedure/runbook.
- Status: `FAIL` (policy not documented in repo)
- Owner:
- Target date:

---

## E. Testing and Monitoring

### E1. Receipt end-to-end tests
- Severity: `High`
- Risk if missing: real-world failures are not caught before production.
- Pass criteria:
1. Integration tests cover upload/download/delete success paths.
2. Tests cover failure paths (disk write failure, invalid content, mid-replace failure).
3. Tests verify DB-file consistency after failures.
- Evidence:
1. Test file list and results from CI/local run.
- Status: `FAIL` (current tests mostly verify route/structure presence)
- Owner:
- Target date:

### E2. Alerting for backup/integrity failures
- Severity: `High`
- Risk if missing: failures happen silently until audit or incident.
- Pass criteria:
1. Backup failure alerts are sent to designated contacts.
2. Integrity scan failures alert same day.
3. Escalation path documented.
- Evidence:
1. Alert configuration.
2. Test alert screenshot/log.
- Status: `FAIL` (logging exists; alert escalation not formalized)
- Owner:
- Target date:

---

## Pre-Go-Live Decision Gate

Go-live recommendation:
- `NO-GO` if any `Critical` item is `FAIL`.
- `Conditional GO` only if all `Critical` are `PASS` and each `High` `FAIL` has signed risk acceptance and due date.
- `GO` when all `Critical` and `High` are `PASS`.

Sign-off:
- Technical owner:
- Operations owner:
- Data protection/compliance owner:
- Date:

---

## Immediate priorities for this project

1. Implement atomic receipt replace.
2. Implement combined DB + receipt backups.
3. Set up off-site copy for combined backups.
4. Run first restore drill and record evidence.
5. Add nightly integrity scan with reporting.

