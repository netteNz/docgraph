# Rolling Back A Promoted Model

Operator runbook for rolling back a promoted model to a previous checkpoint.
The helper functions live in `src/rollback_tools.py`.

## When to roll back a promoted model

A promoted model should be rolled back when post-promotion monitoring shows
the promoted model performing worse than the previous model it replaced.
Roll back a promoted model when the promoted model's live error rate exceeds
the previous model's error rate for a sustained window, when the promoted
model emits malformed predictions, or when the promoted model's latency
regresses badly enough to breach the serving deadline.

Do not roll back a promoted model for a single transient spike. A rollback
is itself a promotion event and carries the same risk of disruption as the
original promotion did. Confirm the regression persists across at least
three consecutive monitoring windows before deciding to roll back the
promoted model, and record the decision in the promotion log so the rollback
can be audited later against the promotion it reverses.

The monitoring windows that justify a rollback must be windows in which the
promoted model actually served meaningful traffic. A promoted model that was
promoted into a quiet period will show a noisy error rate that looks like a
regression but is not one, and rolling back a promoted model on that
evidence replaces a good model with an older one for no reason. Weight the
rollback decision by served volume, not by wall-clock time since promotion.

Escalate rather than roll back when the promoted model's regression is
ambiguous. An operator who rolls back a promoted model has made a production
change, and an unnecessary rollback is as much an incident as a bad
promotion. The rollback guide generator records the justification precisely
so that this judgment is reviewable after the fact.

## Deciding which previous model to roll back to

The rollback target is normally the model that the promoted model replaced,
but it is not always the right previous model to roll back to. If several
promotions happened in quick succession, the immediately previous model may
share the same defect as the promoted model, and rolling back to it simply
reproduces the regression one promotion earlier.

Walk the promotion log backward and pick the most recent previous model that
was live long enough to have produced a clean monitoring record. Record why
that previous model was chosen over the immediately preceding one, because
the rollback guide will reproduce that reasoning for the operator who
executes the rollback and for whoever reviews the promotion history later.

A previous model that has never served production traffic is not a valid
rollback target regardless of how good its offline evaluation looked. The
whole point of rolling back a promoted model is to return to a known-good
serving state, and a model with no serving history is not known-good. If no
previous model in the log qualifies, the correct action is to disable the
promotion pipeline and escalate, not to roll back to an unproven model.

Note that rolling back a promoted model across a schema change is a
different and much more dangerous operation than an ordinary rollback. If
the promoted model changed the feature schema, the previous model cannot
consume the current feature stream, and rolling back the promoted model
requires rolling back the feature pipeline in the same operation.

## Preparing the rollback

Before rolling back a promoted model, confirm the previous model's artifact
is still present in the artifact store and that its checksum matches the
checksum recorded at its original promotion. A rollback that targets a
missing or corrupted previous model artifact will fail partway through and
leave the serving tier in a worse state than the promoted model it was
trying to replace.

Drain in-flight requests, quiesce the promotion pipeline so that no
competing promotion can race the rollback, and snapshot the current promoted
model's configuration so that the rollback itself can be reverted if rolling
back turns out to be the wrong call. A rollback with no path back to the
promoted model is a one-way door, and one-way doors do not belong in a
routine operational procedure.

Verify that the previous model's serving dependencies are still satisfied.
A previous model promoted months ago may expect a feature that has since
been retired, a tokenizer version that has since been upgraded, or a runtime
image that has since been garbage collected. Rolling back a promoted model
to a previous model whose dependencies no longer resolve produces an outage
rather than a recovery.

Finally, announce the rollback before executing it. An operator rolling back
a promoted model silently will be fighting an autoscaler, a scheduled
promotion, or another operator within minutes.

## Executing the rollback

Execute the rollback by pointing the serving alias at the previous model's
artifact, then verify the alias resolves to the intended previous model
before re-admitting traffic. Re-admit traffic gradually rather than all at
once, so that a bad rollback target is caught at low volume rather than
across the entire serving tier.

Watch the same monitoring signals that triggered the rollback and confirm
they return to the previous model's historical baseline. If they do not, the
promoted model was probably not the cause of the regression, and the
rollback should itself be reverted while the real cause is investigated.
Rolling back a promoted model that was innocent leaves the real regression
in place while also discarding a better model.

Hold the promotion pipeline quiesced until the rollback has been confirmed
stable. A scheduled promotion that fires during a rollback will promote a
model on top of a serving tier that is still converging, and the resulting
state is not attributable to either the promotion or the rollback.

## After the rollback

Once the rollback is complete and traffic is stable on the previous model,
write the rollback into the promotion log as a first-class event, including
the promoted model that was rolled back, the previous model rolled back to,
the reason, and the monitoring evidence that justified it.

Block the rolled back promoted model from being re-promoted automatically
until its defect is understood. Otherwise the next scheduled promotion will
promote the same bad model again, and the operator will roll back the same
promoted model twice for the same reason, which is how a single bad model
turns into a recurring incident.

Treat the rollback as the beginning of an investigation rather than the end
of one. The rollback restored service, but the promoted model was promoted
because it passed the promotion gates, so the promotion gates failed to
catch whatever the monitoring caught afterward. A rollback that does not
result in a tightened promotion gate will be followed by another rollback.

## Rolling back a promoted model in a multi-region deployment

A promoted model in a multi-region deployment is rolled back one region at a
time, never globally in a single operation. Roll back the region with the
clearest regression signal first, confirm the previous model restores that
region's baseline, and only then roll back the promoted model in the
remaining regions.

Rolling back a promoted model globally in one step removes the comparison
that proves the rollback worked. With one region rolled back and the others
still serving the promoted model, the difference between them is direct
evidence about whether the promoted model caused the regression. Discarding
that evidence to save a few minutes is a poor trade during an incident.

Expect the regions to disagree. A promoted model can regress in one region
and not another because traffic mix, not the model, differs between them. A
promoted model that regresses in exactly one region is more likely to be a
regional data problem than a bad model, and rolling back the promoted model
everywhere will not fix it.

## Verifying a completed rollback

A rollback is not complete when the alias flips. It is complete when the
previous model is serving all intended traffic, the promoted model is
serving none, and the monitoring signals that triggered the rollback have
returned to the previous model's established baseline for a full window.

Verify each of those three conditions independently. An alias that resolves
correctly while a stale cached handle keeps routing to the promoted model is
a common and badly confusing failure, because the rollback appears complete
in configuration while the promoted model is still serving in practice.

Record the verification evidence alongside the rollback entry in the
promotion log. The next operator rolling back a promoted model will reach
for this runbook, and the most useful thing it can contain is a concrete
record of what a verified rollback looked like the last time one was done.
