# Hax monitor → private create dispatch

This public repository **only reads availability pages**. It never logs
in to Hax or handles Telegram OTP/VPS passwords.

Valid Hax monitor deltas (new datacenter option or decrease in the
observed VPS count) produce a `repository_dispatch` event of type
`hax_create_candidate` to the private `ParsifalC/moyu-renew`
repository. Permanent form options and baseline snapshots do not trigger
creation. The private repo checks signal age, origin and fingerprint
before deciding whether a create attempt is safe.

## Data center policy

**US-3 → EU-1 → US-2** (`US-OpenVZ-3` → `EU-1` → `US-OpenVZ-2`). Only these three Hax data centers are eligible. If only one of them produces a signal, try that one immediately. If several are candidates, prefer the highest-priority choice present in the authenticated Create VPS form; do not wait for US-3 if only EU-1 or US-2 is available. Unknown locations are ignored. The public page may hide Create VPS choices until login; a fresh `/data-center` population decrease is still a candidate event, but the private runner validates the dropdown before submission.

## Configuration (disabled by default)

Public Resources **Actions secret**:
- `HAX_CREATE_DISPATCH_TOKEN`: fine-grained PAT scoped to
  `ParsifalC/moyu-renew` only, with Contents: Read and write.

Public Resources **Actions variable**:
- `HAX_CREATE_DISPATCH_ENABLED=true`.

Merge the private renew implementation first, then merge this branch.
Without both settings, monitoring remains read-only and never dispatches.
A failed API dispatch is retried while the event is fresh, with the same
event fingerprint. Pending events are retained in the `monitor-state`
snapshot and discarded after 15 minutes. No login details are stored
in this public repository. Do not enable creation until the private
repository has the VPS password secret and its tests pass.

Disable dispatch immediately by setting the Actions variable to false.

## Warm private executor (optional)

The default target remains GitHub Actions. For a warm Debian/Ubuntu worker,
set repository variable `HAX_CREATE_WORKER_URL=https://YOUR_HOST/candidate`
and secret `HAX_CREATE_WORKER_TOKEN` matching the private worker token.
The existing `HAX_CREATE_DISPATCH_ENABLED` switch governs both routes.
Only stock metadata is sent. Hax credentials remain on the private worker.
A configured worker replaces Actions delivery; failures retain the same pending
signal for retry and do not launch a second Actions consumer.

Monitoring defaults to 300 seconds during normal hours. Only the existing
16:55–17:20 UTC cleanup window (00:55–01:20 Asia/Shanghai) uses the shorter
15-second interval.
`HAX_INTERVAL_SECONDS` and `HAX_CLEANUP_INTERVAL_SECONDS` repository variables
can override these intervals. Probe duration still adds detection latency.
Stock dispatch runs before the Feishu notification request.

## End-to-end preflight

After merging both repositories, run **Hax Create Dispatch CI** manually with
`dispatch_probe=true`. It sends a synthetic candidate through the same private
repository dispatch API and the same `HAX_CREATE_DISPATCH_TOKEN`, with
`inspect_only=true`. The private workflow still validates the source, timestamp
and event digest, logs in and checks the real form, but never submits a VPS.
This explicit probe does not enable the regular monitoring switch and does not
use the optional warm-worker route. After it passes, enable automatic dispatch
and restart the long-lived monitor so its environment and code are refreshed.
