# Security policy

## Reporting a vulnerability

Please use GitHub private vulnerability reporting for this repository. Do
not open a public issue or include credentials, API keys, personal data, or
exploit details in public discussions.

Reports should include the affected component, reproducible steps, expected
impact, and any suggested mitigation. The maintainer will review the report
and coordinate disclosure after a fix is available.

This repository does not publish a security mailbox; no email address is
invented here.

## Browser response policy

Content Security Policy is intentionally omitted because a single restrictive
policy would break the Swagger UI under `/docs` and the bundled demo page.
Defining separate, tested policies for those surfaces remains an accepted
residual risk; this hardening change does not claim CSP coverage.
