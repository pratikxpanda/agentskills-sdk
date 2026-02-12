# Escalation Policy

## On-Call Rotation

| Team | Primary | Secondary | Schedule |
| --- | --- | --- | --- |
| Platform | Current on-call (PagerDuty) | Backup on-call (PagerDuty) | Weekly rotation, handoff Monday 10am |
| Backend | Current on-call (PagerDuty) | Backup on-call (PagerDuty) | Weekly rotation, handoff Monday 10am |
| Frontend | Current on-call (PagerDuty) | Backup on-call (PagerDuty) | Bi-weekly rotation |

## Escalation by Severity

### SEV1 — Critical

1. **0 min**: Page primary on-call for the affected service
2. **5 min**: If no acknowledgment, page secondary on-call
3. **15 min**: If no acknowledgment, page Engineering Manager
4. **30 min**: Notify Engineering Director and VP Engineering
5. **60 min**: Notify CTO

### SEV2 — High

1. **0 min**: Page primary on-call for the affected service
2. **15 min**: If no acknowledgment, page secondary on-call
3. **30 min**: If no acknowledgment, page Engineering Manager
4. **2 hours**: Notify Engineering Director if unresolved

### SEV3 — Medium

1. **0 min**: Assign to team queue
2. **4 hours**: If unacknowledged, notify team lead
3. **24 hours**: If unresolved, escalate to Engineering Manager

### SEV4 — Low

1. Track in backlog — no escalation required

## Management Notification Rules

- **SEV1**: VP Engineering and CTO notified within 1 hour
- **SEV2**: Engineering Director notified if unresolved after 2 hours
- **SEV3/4**: No management notification unless pattern emerges

## Cross-Team Escalation

When an incident spans multiple teams:

1. Page the primary on-call for each affected team
2. Designate a single Incident Commander (highest severity team owns IC role)
3. All teams join the shared incident channel
4. IC has authority to pull in additional engineers as needed
