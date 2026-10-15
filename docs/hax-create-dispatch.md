# Hax monitor → private create dispatch

This public repository **only reads availability pages**. It never logs
in to Hax or handles Telegram OTP/VPS passwords.

Valid Hax monitor deltas (new datacenter option or decrease in the
observed VPS count) produce a `repository_dispatch` event of type
`hax_create_candidate` to the private `ParsifalC/moyu-renew`
repository. Permanent form options and baseline snapshots do not trigger
creation. The private repo checks signal age, origin and fingerprint
before deciding whether a create attempt is safe.

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
