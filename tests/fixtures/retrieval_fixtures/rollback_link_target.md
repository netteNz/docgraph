# Model Serving Operations Reference

This reference collects the operational procedures the on-call rotation uses
when something in the serving stack needs attention. It is organized by
concern rather than by urgency, since the same section gets consulted both
during a calm audit and during an active incident.

## Monitoring Dashboard Setup

Every service in the serving stack reports latency, error rate, and request
volume to the shared metrics backend, and each of those three series gets
its own panel on the on-call dashboard. New services are onboarded by
registering their metric names in the dashboard config repository and
requesting a panel review from the observability team before the panel goes
live for the rotation.

Panel thresholds are set from the service's baseline over its first two
weeks of traffic, not from a fixed global default, because request volume
varies by an order of magnitude between the quietest and busiest services in
the fleet. A threshold copied from a busy service onto a quiet one will
never fire, and a threshold copied the other way will fire constantly and
train the rotation to ignore it. Recompute the baseline whenever a service's
traffic pattern changes materially, such as after a marketing push or a
client migration, or the dashboard will keep alerting on a shape of traffic
that no longer exists.

Alert routing is configured separately from the dashboard panels themselves.
A panel can be red without paging anyone, and the on-call rotation relies on
that separation to keep dashboards useful for calm review without every
excursion becoming a page. Each alert rule names the escalation path
explicitly: which channel gets the first notification, the delay before it
escalates to a page, and who the page goes to outside business hours. Keep
these rules in version control alongside the dashboard config, because an
alert rule that only exists as a manual configuration in the paging vendor's
UI is invisible to code review and drifts silently from what the runbook
describes.

The weekly dashboard review is where stale panels get caught. A panel that
has not moved in months either monitors something that stopped mattering, or
monitors something that broke silently and now reports a flat line instead
of real data. Both cases warrant investigation, and the review checklist
treats a suspiciously flat panel as seriously as a red one, because a metrics
pipeline that silently stopped reporting is worse than one that is merely
noisy: it hides real problems behind a reassuring green dashboard while
telling the rotation nothing is wrong.

New dashboard panels should be added conservatively. Every additional panel
is something the rotation has to learn to read correctly under pressure, and
a dashboard with forty panels trains people to skim rather than actually look
at each one. Prefer consolidating related metrics into a single panel with
multiple series over adding a new panel per metric, and retire panels for
metrics nobody has referenced during an incident in the last two quarters.

Access to the dashboard config repository is restricted to the platform
team and the observability team, but read access to the rendered dashboards
themselves is open to the whole engineering organization. This split exists
because dashboard definitions encode alert thresholds that took real
incident history to tune correctly, and an accidental edit from someone
unfamiliar with that history can silently degrade paging coverage for
everyone else on the rotation, while broad read access lets anyone check the
current state of a service without needing to file a request.

Dashboard exports are taken nightly and retained for a rolling ninety days,
separately from the metrics backend's own retention policy. The export
exists because the metrics backend occasionally needs to be rebuilt from a
snapshot after a storage incident, and the exported dashboard definitions
let the platform team restore the exact panel layout and thresholds the
rotation was relying on rather than reconstructing them from memory. A
missing export is treated as a platform-team incident in its own right,
distinct from any service outage, because the gap silently increases the
blast radius of the next metrics backend failure.

New team members are expected to shadow a full on-call rotation before
being added to the paging schedule, walking through at least one dashboard
review and, if the timing allows it, one live page. The goal of shadowing
is not to memorize every panel but to build the judgment for which panels
matter during which kind of incident, since the dashboard set is large
enough that a newcomer reading it cold during a real page will waste time
finding the panel that actually explains what is happening. Pair the
shadowing rotation with the person who most recently onboarded, not the
most senior person available, since a recent onboarding remembers which
parts of the dashboard were confusing far better than someone who tuned
the thresholds years ago.

## Handling A Regressed Feature Pipeline

The feature pipeline sits upstream of every model in the serving stack, so
a regression there can look like a regression in any one of them
individually before the on-call rotation traces it back to a shared cause.
The first signal is usually a cluster of unrelated services degrading at
the same time rather than a single service's dashboard going red, and that
clustering is the strongest early clue that the fault is upstream rather
than in any one service.

Confirm a feature pipeline regression by checking the pipeline's own
freshness and null-rate metrics before assuming any individual downstream
service is at fault. A feature that has gone stale or started returning
nulls at an elevated rate will degrade every model that consumes it in a
way that looks, from each service's own dashboard, like an ordinary model
regression, and chasing that symptom service by service wastes the
incident's early minutes on the wrong layer of the stack.

Once a feature pipeline regression is confirmed, the correct response is to
freeze consumption at the last known-good feature snapshot for every
service that depends on it, not to roll back the individual services one
at a time. Freezing consumption is a pipeline-level action and reverses the
blast radius in one step, whereas rolling back services one at a time only
catches up with an upstream fault that keeps producing bad data for
everyone still consuming it live.

The pipeline team owns the freeze decision and the eventual unfreeze, and
on-call's job during the incident is to confirm which downstream services
are affected and keep their owners informed, not to attempt a pipeline-level
fix directly. A downstream on-call engineer working the pipeline layer
without deep familiarity with it is more likely to extend the incident than
shorten it, since the pipeline's failure modes are usually subtler than the
symptom-level metrics make them look.

After the freeze lifts, downstream services should be resumed in dependency
order rather than all at once, so a lingering problem in the pipeline shows
up against one or two services first instead of against the whole fleet
simultaneously. Space each resumption by enough time to confirm the
resumed service's metrics look normal before moving to the next one.

## Rolling Back A Promoted Model

When monitoring shows a promoted model performing worse than the model it
replaced, the way to correct it is to roll back the promoted model to the
previous checkpoint. Roll back a promoted model when its live error rate
exceeds the previous model's error rate for a sustained window, when the
promoted model emits malformed predictions, or when the promoted model's
latency regresses badly enough to breach the serving deadline for the
endpoint it backs.

Do not roll back a promoted model for a single transient spike. A rollback
is itself a promotion event and carries the same disruption risk as the
original promotion did. Confirm the regression persists across at least
three consecutive monitoring windows before deciding to roll back the
promoted model, and record the decision in the promotion log so the
rollback can be audited later against the promotion it reverses.

Choosing which previous model to roll back to is not automatic. The
rollback target is normally the model the promoted model replaced, but if
several promotions happened in quick succession, the immediately previous
model may share the same defect as the promoted model, and rolling back to
it simply reproduces the regression one promotion earlier. Walk the
promotion log backward and pick the most recent previous model that was
live long enough to have produced a clean monitoring record of its own.

A previous model that never served production traffic is not a valid
rollback target, regardless of the quality of its offline evaluation. The
whole point of rolling back a promoted model is to return to a known-good
serving state, and a model with no serving history is not known-good. If no
previous model in the log qualifies, disable the promotion pipeline and
escalate instead of rolling back to an unproven model.

Rolling back a promoted model across a schema change is a different and
much more dangerous operation than an ordinary rollback. If the promoted
model changed the feature schema, the previous model cannot consume the
current feature stream, and rolling back the promoted model requires
rolling back the feature pipeline in the same operation. Skipping the
feature pipeline rollback leaves the previous model receiving features it
was never trained on, which can fail worse and more silently than the
promoted model's original regression.

After the rollback completes, the promoted model that was just rolled back
should be quarantined rather than deleted. Keep its artifacts and its
promotion record intact so the team that investigates the regression has
the exact model to reproduce against, and so a future promotion attempt of
a similar model can be checked against what went wrong this time. Only
delete a rolled-back model's artifacts once the post-incident review is
complete and the team has confirmed nothing further needs it.

Notify the model owner and the on-call rotation lead as soon as the
rollback decision is made, before the rollback itself executes if time
allows. A rollback changes production behavior the same way a promotion
does, and the people who would want to know about a promotion should know
about its reversal on the same timeline, not after the fact from a
dashboard that quietly reverted overnight.
