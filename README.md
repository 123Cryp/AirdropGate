# AirdropGate

Claim-verified airdrops on GenLayer. A sponsor funds a campaign with real GEN and publishes eligibility criteria plus the URL prefixes that count as evidence. Anyone can claim by pointing to an evidence page that names their address. GenLayer validators fetch that page themselves, check it against the criteria, and must agree before any GEN becomes payable. Anyone can challenge an approval by staking a bond and citing counter-evidence.

## What is different from escrow / dispute contracts

There are no two parties to a deal. One funded pool serves many strangers, and the open problem is sybil and false claims. The contract answers it with three layers, each enforced in code rather than trusted to the model:

1. **Address anchor.** The claimant's own address must appear in the fetched evidence page, checked in deterministic code. The model can never approve a page that does not mention the claimant.
2. **Grounded verdict.** An ELIGIBLE verdict is downgraded to UNDETERMINED unless the model returns an exact quote that really occurs in the fetched page.
3. **Bonded challenge.** Any third party can stake 2 GEN against an approval during the challenge window. The claim is re-judged with the counter-evidence. An upheld challenge pays the bond back plus a bounty; a failed one forfeits the bond to the claimant.

## Contract

`contracts/airdropgate.py` (single file, deploy as is). Constructor argument: `min_window_seconds` (use `60` for testing, `3600` for production).

| Method | Who | Purpose |
|---|---|---|
| `create_campaign(title, criteria, evidence_prefixes, reward_gen, claim_window_seconds, challenge_window_seconds)` payable | sponsor | fund a campaign; invalid input is refunded to the caller's balance, not reverted |
| `submit_claim(campaign_id, evidence_url)` | claimant | reserve one reward slot, one claim per address per campaign |
| `evaluate_claim(campaign_id, claimant)` | anyone | consensus verification of the evidence page |
| `appeal_denial(campaign_id, new_evidence_url)` | claimant | one appeal after a denial |
| `challenge_claim(campaign_id, claimant, counter_evidence_url)` payable, 2 GEN | anyone but claimant | dispute an approval |
| `resolve_challenge(campaign_id, claimant)` | anyone | consensus re-judgment with counter-evidence |
| `cancel_challenge(campaign_id, claimant)` | anyone | refund a challenge that stayed unresolved for 3 days |
| `finalize(campaign_id, claimant)` | anyone | pay an unchallenged approval or close a denial |
| `expire_claim(campaign_id, claimant)` | anyone | release the slot of a claim stuck in verification for 3 days |
| `reclaim_unused(campaign_id)` | sponsor | take back unreserved budget after the claim window |
| `withdraw()` | anyone | pull payment of the caller's balance |

Views (all return JSON strings): `get_params`, `get_stats`, `list_campaigns`, `get_campaign`, `list_claims`, `get_claim`, `list_claims_by`, `get_balance`, `get_accounting`.

## Deployment

Deployed on GenLayer Studio at `0xfD0cc02e5015F1bcAB38AC8865020aa7EFF51DEb`. The contract is submitted on its own; there is no frontend in this repository. `evidence/list.txt` is a sample evidence page used for live testing.

## Tests

```
python3 -m unittest discover -s tests -p "test_*.py"
```

No pip install is needed. The suite runs against a small offline stand-in for the GenLayer SDK (`tests/genlayer_stub.py`) and checks, after every call, that the contract's real GEN balance equals its recorded obligations.

See `ARCHITECTURE.md` for the state machine, accounting and trust assumptions.

## License

MIT
