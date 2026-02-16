---
name: incident-response
description: Standard operating procedures for production incident management including severity classification, escalation paths, communication protocols, and postmortem processes.
---

# Incident Response

This skill provides structured guidance for handling production incidents.

## When to Declare an Incident

An incident should be declared when:

- A production service is degraded or unavailable for users
- Data integrity may be compromised
- A security breach is suspected
- SLA thresholds are at risk of being violated

## Roles

| Role | Responsibility |
|---|---|
| **Incident Commander (IC)** | Owns the incident lifecycle, coordinates response, makes decisions |
| **Communications Lead** | Keeps stakeholders informed, posts status updates, manages the incident channel |
| **Technical Lead** | Drives root cause investigation, coordinates engineering fixes |

## General Triage Steps

1. **Acknowledge** - Confirm you are responding to the alert
2. **Assess** - Determine severity using the severity-levels reference
3. **Communicate** - Open an incident channel and notify stakeholders
4. **Escalate** - Follow the escalation policy based on severity
5. **Mitigate** - Apply immediate fixes to restore service
6. **Resolve** - Confirm the issue is fully resolved and monitoring is clean
7. **Postmortem** - Schedule and complete a blameless postmortem within 48 hours

## Communication Expectations

- Status updates every **15 minutes** for SEV1, **30 minutes** for SEV2
- All communication happens in the incident Slack channel
- External customer communication is handled by the Communications Lead
- Management is notified per the escalation policy

## Available References

- `severity-levels.md` - Severity definitions (SEV1-SEV4) with impact and response times
- `escalation-policy.md` - Who to page per severity level and escalation timelines
- `postmortem-template.md` - Structured template for blameless postmortems

## Available Scripts

- `page-oncall.sh` - Page the on-call engineer via PagerDuty API
- `create-incident-channel.sh` - Create a dedicated Slack incident channel

## Available Assets

- `escalation-flowchart.mermaid` - Visual flowchart of the escalation process
