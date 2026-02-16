# Severity Levels

## SEV1 - Critical

- **Impact**: Complete service outage or data loss affecting all users
- **Response time**: 15 minutes
- **Examples**: Database corruption, full site down, payment processing failure, security breach with active exploitation
- **On-call expectation**: Immediate response. All hands on deck. Incident Commander required.
- **Communication cadence**: Every 15 minutes until mitigated
- **Auto-escalation**: If not acknowledged in 15 minutes, escalate to Engineering Director

## SEV2 - High

- **Impact**: Major feature degraded, significant subset of users affected
- **Response time**: 30 minutes
- **Examples**: Search not returning results, login failing for 30% of users, API latency >10s for a core endpoint
- **On-call expectation**: Immediate response. Technical Lead and IC required.
- **Communication cadence**: Every 30 minutes until mitigated
- **Auto-escalation**: If not acknowledged in 30 minutes, escalate to Engineering Manager

## SEV3 - Medium

- **Impact**: Minor feature degraded, small subset of users affected, workaround available
- **Response time**: 4 hours (business hours)
- **Examples**: Dashboard rendering slowly, export feature timing out for large datasets, non-critical alert firing
- **On-call expectation**: Respond during business hours. Single engineer sufficient.
- **Communication cadence**: At start and resolution
- **Auto-escalation**: If not resolved in 24 hours, escalate to team lead

## SEV4 - Low

- **Impact**: Cosmetic issues, minor bugs, no user-facing impact
- **Response time**: Next sprint
- **Examples**: Typo in error message, minor UI misalignment, log noise from a deprecated endpoint
- **On-call expectation**: No on-call response needed. Track in backlog.
- **Communication cadence**: None required
- **Auto-escalation**: None
