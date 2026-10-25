# Future technology evaluation

This is a design evaluation against the current application. No hardware pilot, campus identity integration or measured user trial is claimed.

| Candidate | User need and compatibility | Security/operational questions | Decision for this submission |
| --- | --- | --- | --- |
| Barcode/QR-assisted physical-unit lookup | Could reduce identifier entry at handover. The existing unit identifier remains authoritative and the current service validation must remain in place. | Test actual campus labels/readers, incorrect scans, manual fallback and keyboard/mobile use. Camera use would need an appropriate permission flow. Never encode passwords or private borrower data in labels. | Consider a small custodian-led prototype after the required course workflows are accepted. No scanning dependency is added now. |
| Institutional single sign-on | Could reduce separate campus credentials while retaining the application's two roles and deactivation rules. Campus identity capabilities and permission to integrate are currently unknown. | Require institution approval, verified role mapping, account lifecycle/revocation behavior, recovery, test identities and a migration plan for existing accounts. | Defer until the institution supplies requirements and an authorized test integration. |

The current server-rendered Django implementation meets the local demonstration workflow with existing forms, permissions and transactional services. Adoption should depend on measured task time, error rate, accessibility feedback, security review and maintenance ownership. The team must record trial results and explain whether evidence changes these recommendations before claiming an empirical evaluation is complete.
