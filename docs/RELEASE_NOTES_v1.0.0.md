# ReportFlow Desktop v1.0.0

**Release status:** Release candidate  
**Target:** Windows desktop distribution  
**Package:** `ReportFlow-Windows.zip` containing `ReportFlow.exe`

## Overview

ReportFlow Desktop v1.0.0 transforms the original reporting script into a professional, local-first desktop application for producing repeatable business reports from CSV and Excel sources. It provides a polished report-building workflow, data quality signals, reusable definitions, auditable execution evidence, daily local scheduling, secure credential-reference handling, and validated HTML, PDF, and Excel output.

## Highlights

| Area | Included in v1.0.0 |
|---|---|
| Report creation | Executive, Financial, Operational, and Client-facing templates with configurable source fields and output formats |
| Data readiness | Preview of CSV/XLS/XLSX sources, row/field counts, missing cells, duplicate rows, and numeric-field detection |
| Deliverables | Branded HTML, print-ready PDF, and Excel workbook output with a trend chart and validated source table |
| Repeatability | Local report catalog, one-click reruns, daily scheduling, and an append-only local audit trail |
| Security foundation | Operating-system credential vault integration; report records contain only credential references, never secret values |
| Distribution engineering | GitHub Actions build on Windows, automated tests, dependency audit, package verification, and a SHA-256 check in CI |

## Validation

| Validation | Result |
|---|---|
| Core and UI smoke tests | Passed: 4 tests |
| Dependency vulnerability audit | Passed: no known vulnerabilities in declared runtime requirements |
| Windows runner build | Passed on `windows-latest` |
| `ReportFlow.exe` verification | Passed |
| Windows package artifact upload | Passed |

## Known constraints

This is a **local single-user release**. Data connectors currently support CSV and Excel files, and scheduled jobs run while the desktop application is available on the workstation. SSO, centralized scheduling, server-managed secrets, recipient-level bursting, collaboration workflows, and enterprise policy enforcement are intentionally planned as the next commercial milestones; they are not represented as delivered features in v1.0.0.

## Upgrade and installation

1. Download `ReportFlow-Windows.zip` from the release assets.
2. Extract the archive to a directory where the user has write access.
3. Run `ReportFlow.exe`.
4. Load a CSV/XLS/XLSX source or choose the local sample dataset.
5. Create and save a report definition, then generate PDF, Excel, and/or HTML deliverables.

> The first commercial production rollout should include Windows code signing and an organization-approved installer. This release is a functional, validated release candidate package; it is not code-signed.

## Security notice

Do not commit credentials or long-lived access tokens to the repository. Tokens shared during development should be rotated after the release process is complete. For Enterprise deployment, follow the access-control and desktop-security controls described in the [Commercial Roadmap](COMMERCIAL_ROADMAP.md).
