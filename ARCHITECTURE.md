# AirdropGate architecture

## Entities

- **Campaign**: sponsor, title, public criteria, 1-5 evidence URL prefixes, reward per claim, budget, windows. Budget accounting: `free = budget - reserved - spent - refunded`.
- **Claim**: keyed `campaignId:claimantAddress`, so a second claim from one address is impossible by construction.

## Claim state machine

```
submit_claim -> PENDING
PENDING --evaluate ELIGIBLE--> ELIGIBLE_PROPOSED
PENDING --evaluate NOT_ELIGIBLE--> DENIED
PENDING --evaluate UNDETERMINED--> PENDING (attempts+1; 3rd attempt -> REJECTED)
PENDING --stale 3 days, expire_claim--> REJECTED
DENIED --appeal_denial (once, before appeal_end)--> PENDING
DENIED --finalize after appeal_end--> REJECTED
ELIGIBLE_PROPOSED --challenge_claim (once, before challenge_end)--> CHALLENGED
ELIGIBLE_PROPOSED --finalize after challenge_end--> PAID
CHALLENGED --resolve NOT_ELIGIBLE--> REJECTED (challenger gets bond + 10% of reward)
CHALLENGED --resolve ELIGIBLE--> ELIGIBLE_PROPOSED, finalizable now (claimant gets bond)
CHALLENGED --resolve UNDETERMINED--> ELIGIBLE_PROPOSED, finalizable now (bond refunded)
CHALLENGED --stale 3 days, cancel_challenge--> ELIGIBLE_PROPOSED, finalizable now (bond refunded)
```

Every state has a path to a terminal state without trusting any single party, so no reward slot or bond can stay locked forever.

## Verification

`_evaluate` runs identically on the leader and every validator:

1. Fetch the evidence page (and the counter-evidence page for a challenge). A failed fetch is UNDETERMINED.
2. Deterministic anchor: the claimant address must occur in the page, otherwise NOT_ELIGIBLE without any model call.
3. Ask the model for `{verdict, quote, reason}`. The page text is declared untrusted in the prompt.
4. Grounding: ELIGIBLE needs a quote of at least 12 characters that occurs in the page after whitespace normalisation, otherwise UNDETERMINED.

Consensus uses `gl.vm.run_nondet_unsafe(leader, validator)` with module-level functions (no contract `self` captured). The validator re-derives its own verdict and requires the same categorical verdict as the leader; the quote and reason are leader-attested. All errors are caught inside the nondet closures and turned into ordinary UNDETERMINED strings.

## Evidence URL rules

Evidence must be https, carry no credentials, use no non-443 port, contain no `..`, `%2e` or `%2f`, and, after lower-casing the host and dropping the fragment, start with one of the campaign's prefixes. Prefixes are validated at creation (https, end with `/`, no query). Look-alike hosts and `host@evil` forms are rejected by the parsed-URL checks.

## Money

All amounts are wei internally; users enter whole GEN (`reward_gen`, payable value). Payouts are pull-based: `finalize` and the challenge outcomes only credit `balances`, `withdraw` transfers. Payable methods never revert on bad input; they credit the attached value back to the caller's balance. Invariant checked in tests after every call:

```
contract balance == sum(campaign budget - refunded - spent) + sum(balances) + sum(open challenge bonds)
```

`get_accounting` exposes both sides.

## Trust assumptions

- The sponsor is trusted to choose evidence prefixes under content they control. A prefix on a place where anyone can publish lets claimants author their own proof.
- Validators are trusted only for the categorical verdict; code enforces anchoring, grounding, authorization, windows and accounting.
- Challenge counter-evidence is limited to the same prefixes, so challengers cite sponsor-controlled or sponsor-approved pages.

## Known limits

- One challenge and one appeal per claim.
- Time comes from `datetime.datetime.now()` as seen by GenVM.
- `MAX_CLAIMS` is 200 per campaign to keep stored records small.
