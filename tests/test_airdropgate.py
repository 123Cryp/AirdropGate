import datetime as real_datetime
import importlib.util
import json
import os
import sys
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import genlayer_stub as stub  # noqa: E402

sys.modules["genlayer"] = stub

CONTRACT_PATH = os.environ.get(
    "AIRDROPGATE_CONTRACT", os.path.join(HERE, "..", "contracts", "airdropgate.py")
)
spec = importlib.util.spec_from_file_location("airdropgate_contract", CONTRACT_PATH)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

CLOCK = [1_800_000_000]


class _FakeDatetimeClass:
    @staticmethod
    def now():
        return real_datetime.datetime.fromtimestamp(CLOCK[0])


mod.datetime = types.SimpleNamespace(datetime=_FakeDatetimeClass)

WEI = 10 ** 18
SPONSOR = "0x1111111111111111111111111111111111111111"
ALICE = "0xAaAaAaAaAaAaAaAaAaAaAaAaAaAaAaAaAaAaAaAa"
BOB = "0xBbBbBbBbBbBbBbBbBbBbBbBbBbBbBbBbBbBbBbBb"
CAROL = "0xCcCcCcCcCcCcCcCcCcCcCcCcCcCcCcCcCcCcCcCc"
DAVE = "0xDdDdDdDdDdDdDdDdDdDdDdDdDdDdDdDdDdDdDdDd"
PREFIX = "https://raw.githubusercontent.com/airdrop-org/list/main/"
CRITERIA = "Eligible if the wallet completed at least three testnet tasks listed on the evidence page."
CHW = 3600
CW = 86400


def page_for(addr, ok=True):
    if ok:
        return "Participant %s qualifies: completed 3 testnet tasks." % addr
    return "Participant %s did only 1 testnet task, not enough." % addr


def url_for(name):
    return PREFIX + name + ".txt"


class Model:
    def __init__(self):
        self.mode = "smart"
        self.fixed = None
        self.flip = False
        self.calls = 0

    def __call__(self, prompt):
        self.calls += 1
        if self.fixed is not None:
            return self.fixed
        if self.flip:
            self.flip = False
            return {"verdict": "ELIGIBLE", "quote": "Participant ... qualifies: completed 3 testnet tasks.", "reason": "x"}
        start = prompt.index("=== CLAIMANT EVIDENCE PAGE START ===") + len("=== CLAIMANT EVIDENCE PAGE START ===")
        end = prompt.index("=== CLAIMANT EVIDENCE PAGE END ===")
        page = prompt[start:end].strip()
        if "COUNTER EVIDENCE PAGE" in prompt and "REVOKED" in prompt:
            return {"verdict": "NOT_ELIGIBLE", "quote": "", "reason": "revoked"}
        if "qualifies" in page:
            return {"verdict": "ELIGIBLE", "quote": page, "reason": "meets criteria"}
        return {"verdict": "NOT_ELIGIBLE", "quote": "", "reason": "does not meet criteria"}


class Base(unittest.TestCase):
    def setUp(self):
        CLOCK[0] = 1_800_000_000
        self.h = stub.Harness(mod.AirdropGate, SPONSOR, 60)
        self.model = Model()
        stub.chain.model = self.model
        for who in (ALICE, BOB, CAROL, DAVE):
            stub.chain.pages[url_for(who[2:8])] = page_for(who)
        self.alice_url = url_for(ALICE[2:8])

    def call(self, sender, method, *args, value=0):
        res = self.h.call(sender, method, *args, value=value)
        self.check_invariant()
        return res

    def check_invariant(self):
        acc = json.loads(self.h.contract.get_accounting())
        self.assertEqual(acc["obligations"], self.h.balance(), acc)

    def create(self, gen_budget=10, reward=2, cw=CW, chw=CHW, prefixes=PREFIX, criteria=CRITERIA):
        cid = self.call(
            SPONSOR, "create_campaign", "Testnet Airdrop", criteria, prefixes, reward, cw, chw,
            value=gen_budget * WEI,
        )
        self.assertTrue(cid.startswith("c"), cid)
        return cid

    def claim(self, who, cid, url=None):
        return self.call(who, "submit_claim", cid, url or url_for(who[2:8]))

    def claim_data(self, cid, who):
        return json.loads(self.h.contract.get_claim(cid, who))

    def camp(self, cid):
        return json.loads(self.h.contract.get_campaign(cid))

    def eligible_claim(self, who=ALICE, cid=None):
        cid = cid or self.create()
        self.claim(who, cid)
        self.call(DAVE, "evaluate_claim", cid, who)
        self.assertEqual(self.claim_data(cid, who)["state"], "ELIGIBLE_PROPOSED")
        return cid


class TestCreate(Base):
    def test_create_ok(self):
        cid = self.create()
        c = self.camp(cid)
        self.assertEqual(c["budget"], 10 * WEI)
        self.assertEqual(c["reward"], 2 * WEI)
        self.assertEqual(c["free"], 10 * WEI)
        self.assertEqual(c["status"], "OPEN")
        self.assertEqual(c["prefixes"], [PREFIX])

    def test_rejections_credit_sender_and_do_not_revert(self):
        bad = [
            ("", CRITERIA, PREFIX, 2, CW, CHW, 5),
            ("t", "short", PREFIX, 2, CW, CHW, 5),
            ("t", CRITERIA, "http://raw.githubusercontent.com/x/", 2, CW, CHW, 5),
            ("t", CRITERIA, "https://user:pw@raw.githubusercontent.com/x/", 2, CW, CHW, 5),
            ("t", CRITERIA, "https://raw.githubusercontent.com/x", 2, CW, CHW, 5),
            ("t", CRITERIA, "", 2, CW, CHW, 5),
            ("t", CRITERIA, PREFIX, 0, CW, CHW, 5),
            ("t", CRITERIA, PREFIX, 6, CW, CHW, 5),
            ("t", CRITERIA, PREFIX, 2, 10, CHW, 5),
            ("t", CRITERIA, PREFIX, 2, CW, 5, 5),
            ("t", CRITERIA, PREFIX, 2, CW, 10 * 86400, 5),
            ("t", CRITERIA, PREFIX, 2, 100 * 86400, CHW, 5),
        ]
        total = 0
        for title, crit, pre, rew, cw, chw, gen in bad:
            res = self.call(SPONSOR, "create_campaign", title, crit, pre, rew, cw, chw, value=gen * WEI)
            self.assertTrue(res.startswith("REJECTED:"), (res, title, pre))
            total += gen * WEI
        self.assertEqual(int(self.h.contract.get_balance(SPONSOR)), total)
        self.assertEqual(json.loads(self.h.contract.get_stats())["campaigns"], 0)
        self.call(SPONSOR, "withdraw")
        self.assertEqual(stub.chain.transfers[-1], (SPONSOR, total))

    def test_too_many_prefixes(self):
        pre = ",".join("https://h%d.example.com/p/" % i for i in range(6))
        res = self.call(SPONSOR, "create_campaign", "t", CRITERIA, pre, 1, CW, CHW, value=2 * WEI)
        self.assertTrue(res.startswith("REJECTED:"))

    def test_prefix_dedup_and_lowercase_host(self):
        cid = self.create(prefixes="https://RAW.GitHubUserContent.com/a/, https://raw.githubusercontent.com/a/")
        self.assertEqual(self.camp(cid)["prefixes"], ["https://raw.githubusercontent.com/a/"])

    def test_constructor_validation(self):
        with self.assertRaises(Exception):
            stub.Harness(mod.AirdropGate, SPONSOR, 0)
        with self.assertRaises(Exception):
            stub.Harness(mod.AirdropGate, SPONSOR, 999999)


class TestSubmitClaim(Base):
    def test_submit_ok_and_reserves(self):
        cid = self.create()
        key = self.claim(ALICE, cid)
        self.assertEqual(key, cid + ":" + ALICE.lower())
        c = self.camp(cid)
        self.assertEqual(c["reserved"], 2 * WEI)
        self.assertEqual(c["free"], 8 * WEI)
        cl = self.claim_data(cid, ALICE)
        self.assertEqual(cl["state"], "PENDING")

    def test_duplicate_sponsor_closed_window(self):
        cid = self.create()
        self.claim(ALICE, cid)
        with self.assertRaises(Exception):
            self.claim(ALICE, cid, url_for("other"))
        with self.assertRaises(Exception):
            self.call(SPONSOR, "submit_claim", cid, url_for("x"))
        CLOCK[0] += CW + 1
        with self.assertRaises(Exception):
            self.claim(BOB, cid)

    def test_url_validation(self):
        cid = self.create()
        bad = [
            "http://raw.githubusercontent.com/airdrop-org/list/main/a.txt",
            "https://raw.githubusercontent.com.evil.com/airdrop-org/list/main/a.txt",
            "https://raw.githubusercontent.com@evil.com/airdrop-org/list/main/a.txt",
            "https://user@raw.githubusercontent.com/airdrop-org/list/main/a.txt",
            "https://raw.githubusercontent.com/airdrop-org/list/main/../../evil/a.txt",
            "https://raw.githubusercontent.com/airdrop-org/list/main/%2e%2e/a.txt",
            "https://raw.githubusercontent.com/airdrop-org/other/main/a.txt",
            "https://raw.githubusercontent.com:8443/airdrop-org/list/main/a.txt",
            "https://raw.githubusercontent.com/airdrop-org/list/main/",
            "https://raw.githubusercontent.com/airdrop-org/list/main/a b.txt",
            "ftp://raw.githubusercontent.com/airdrop-org/list/main/a.txt",
            "",
            "https://raw.githubusercontent.com/airdrop-org/list/main/" + "a" * 400,
        ]
        for u in bad:
            with self.assertRaises(Exception, msg=u):
                self.call(ALICE, "submit_claim", cid, u)
        self.assertEqual(self.camp(cid)["reserved"], 0)

    def test_url_normalized_host_case_and_fragment(self):
        cid = self.create()
        self.call(ALICE, "submit_claim", cid, "https://RAW.githubusercontent.com/airdrop-org/list/main/a.txt#frag")
        self.assertEqual(self.claim_data(cid, ALICE)["evidence_url"], PREFIX + "a.txt")

    def test_no_free_slot(self):
        cid = self.create(gen_budget=4, reward=2)
        self.claim(ALICE, cid)
        self.claim(BOB, cid)
        with self.assertRaises(Exception):
            self.claim(CAROL, cid)
        self.assertEqual(self.camp(cid)["reserved"], 4 * WEI)

    def test_unknown_campaign(self):
        with self.assertRaises(Exception):
            self.call(ALICE, "submit_claim", "c99", self.alice_url)


class TestEvaluate(Base):
    def test_eligible_then_finalize_pays(self):
        cid = self.eligible_claim()
        cl = self.claim_data(cid, ALICE)
        self.assertEqual(cl["verdict"], "ELIGIBLE")
        self.assertIn("qualifies", cl["quote"])
        with self.assertRaises(Exception):
            self.call(DAVE, "finalize", cid, ALICE)
        CLOCK[0] += CHW + 1
        self.assertEqual(self.call(DAVE, "finalize", cid, ALICE), "PAID")
        with self.assertRaises(Exception):
            self.call(DAVE, "finalize", cid, ALICE)
        self.assertEqual(int(self.h.contract.get_balance(ALICE)), 2 * WEI)
        c = self.camp(cid)
        self.assertEqual(c["reserved"], 0)
        self.assertEqual(c["spent"], 2 * WEI)
        self.call(ALICE, "withdraw")
        self.assertEqual(stub.chain.transfers[-1], (ALICE, 2 * WEI))
        with self.assertRaises(Exception):
            self.call(ALICE, "withdraw")
        self.assertEqual(json.loads(self.h.contract.get_stats())["total_paid"], 2 * WEI)

    def test_evaluate_twice_rejected(self):
        cid = self.eligible_claim()
        with self.assertRaises(Exception):
            self.call(DAVE, "evaluate_claim", cid, ALICE)

    def test_address_not_in_page_is_code_level_denial_without_model(self):
        cid = self.create()
        stub.chain.pages[url_for("shared")] = "Participant someone-else qualifies"
        self.call(ALICE, "submit_claim", cid, url_for("shared"))
        before = self.model.calls
        self.call(DAVE, "evaluate_claim", cid, ALICE)
        self.assertEqual(self.model.calls, before)
        cl = self.claim_data(cid, ALICE)
        self.assertEqual(cl["state"], "DENIED")
        self.assertIn("does not appear", cl["reason"])

    def test_model_cannot_override_missing_address(self):
        cid = self.create()
        stub.chain.pages[url_for("shared")] = "no addresses here at all, just text"
        self.model.fixed = {"verdict": "ELIGIBLE", "quote": "no addresses here at all", "reason": "x"}
        self.call(ALICE, "submit_claim", cid, url_for("shared"))
        self.call(DAVE, "evaluate_claim", cid, ALICE)
        self.assertEqual(self.claim_data(cid, ALICE)["state"], "DENIED")

    def test_ungrounded_quote_downgrades_and_third_attempt_rejects(self):
        cid = self.create()
        self.claim(ALICE, cid)
        self.model.fixed = {"verdict": "ELIGIBLE", "quote": "this sentence is not on the page", "reason": "x"}
        for i in range(2):
            self.call(DAVE, "evaluate_claim", cid, ALICE)
            cl = self.claim_data(cid, ALICE)
            self.assertEqual(cl["state"], "PENDING")
            self.assertEqual(cl["attempts"], i + 1)
        self.assertEqual(self.camp(cid)["reserved"], 2 * WEI)
        self.call(DAVE, "evaluate_claim", cid, ALICE)
        self.assertEqual(self.claim_data(cid, ALICE)["state"], "REJECTED")
        self.assertEqual(self.camp(cid)["reserved"], 0)
        self.assertEqual(self.camp(cid)["free"], 10 * WEI)

    def test_short_quote_is_ungrounded(self):
        cid = self.create()
        self.claim(ALICE, cid)
        self.model.fixed = {"verdict": "ELIGIBLE", "quote": "qualifies", "reason": "x"}
        self.call(DAVE, "evaluate_claim", cid, ALICE)
        self.assertEqual(self.claim_data(cid, ALICE)["state"], "PENDING")

    def test_fetch_failure_is_undetermined(self):
        cid = self.create()
        self.call(ALICE, "submit_claim", cid, url_for("missing"))
        self.call(DAVE, "evaluate_claim", cid, ALICE)
        cl = self.claim_data(cid, ALICE)
        self.assertEqual(cl["state"], "PENDING")
        self.assertEqual(cl["verdict"], "UNDETERMINED")

    def test_model_error_is_undetermined(self):
        cid = self.create()
        self.claim(ALICE, cid)
        stub.chain.model = None
        self.call(DAVE, "evaluate_claim", cid, ALICE)
        self.assertEqual(self.claim_data(cid, ALICE)["verdict"], "UNDETERMINED")

    def test_garbage_model_output(self):
        cid = self.create()
        self.claim(ALICE, cid)
        self.model.fixed = "not json at all"
        self.call(DAVE, "evaluate_claim", cid, ALICE)
        self.assertEqual(self.claim_data(cid, ALICE)["state"], "PENDING")
        self.model.fixed = 'noise {"verdict": "NOT_ELIGIBLE", "reason": "no"} noise'
        self.call(DAVE, "evaluate_claim", cid, ALICE)
        self.assertEqual(self.claim_data(cid, ALICE)["state"], "DENIED")

    def test_validator_disagreement_leaves_state_untouched(self):
        cid = self.create()
        self.claim(ALICE, cid)
        self.model.flip = True
        with self.assertRaises(stub.NondetDisagreement):
            self.call(DAVE, "evaluate_claim", cid, ALICE)
        self.assertEqual(self.claim_data(cid, ALICE)["state"], "PENDING")
        self.assertEqual(self.claim_data(cid, ALICE)["attempts"], 0)

    def test_prompt_marks_page_as_untrusted(self):
        seen = []

        def capture(prompt):
            seen.append(prompt)
            return {"verdict": "NOT_ELIGIBLE", "quote": "", "reason": "x"}

        stub.chain.model = capture
        cid = self.create()
        self.claim(ALICE, cid)
        self.call(DAVE, "evaluate_claim", cid, ALICE)
        self.assertIn("untrusted", seen[0])
        self.assertIn(CRITERIA, seen[0])

    def test_pipe_in_model_text_cannot_forge_fields(self):
        cid = self.create()
        self.claim(ALICE, cid)
        self.model.fixed = {"verdict": "NOT_ELIGIBLE", "quote": "", "reason": "a|ELIGIBLE|b"}
        self.call(DAVE, "evaluate_claim", cid, ALICE)
        cl = self.claim_data(cid, ALICE)
        self.assertEqual(cl["verdict"], "NOT_ELIGIBLE")
        self.assertEqual(cl["state"], "DENIED")


class TestAppealAndDenial(Base):
    def make_denied(self):
        cid = self.create()
        stub.chain.pages[url_for("weak")] = page_for(ALICE, ok=False)
        self.call(ALICE, "submit_claim", cid, url_for("weak"))
        self.call(DAVE, "evaluate_claim", cid, ALICE)
        self.assertEqual(self.claim_data(cid, ALICE)["state"], "DENIED")
        return cid

    def test_appeal_success(self):
        cid = self.make_denied()
        stub.chain.pages[url_for("strong")] = page_for(ALICE)
        self.call(ALICE, "appeal_denial", cid, url_for("strong"))
        cl = self.claim_data(cid, ALICE)
        self.assertEqual(cl["state"], "PENDING")
        self.assertEqual(cl["appeals"], 1)
        self.assertEqual(len(cl["history"]), 2)
        self.call(DAVE, "evaluate_claim", cid, ALICE)
        self.assertEqual(self.claim_data(cid, ALICE)["state"], "ELIGIBLE_PROPOSED")

    def test_second_appeal_blocked(self):
        cid = self.make_denied()
        self.call(ALICE, "appeal_denial", cid, url_for("weak"))
        self.call(DAVE, "evaluate_claim", cid, ALICE)
        self.assertEqual(self.claim_data(cid, ALICE)["state"], "DENIED")
        with self.assertRaises(Exception):
            self.call(ALICE, "appeal_denial", cid, url_for("weak"))

    def test_appeal_only_by_claimant_before_deadline_with_valid_url(self):
        cid = self.make_denied()
        with self.assertRaises(Exception):
            self.call(BOB, "appeal_denial", cid, url_for("weak"))
        with self.assertRaises(Exception):
            self.call(ALICE, "appeal_denial", cid, "https://evil.example.com/a.txt")
        CLOCK[0] += CHW + 1
        with self.assertRaises(Exception):
            self.call(ALICE, "appeal_denial", cid, url_for("weak"))

    def test_denial_finalizes_and_releases_slot(self):
        cid = self.make_denied()
        self.assertEqual(self.camp(cid)["reserved"], 2 * WEI)
        with self.assertRaises(Exception):
            self.call(DAVE, "finalize", cid, ALICE)
        CLOCK[0] += CHW + 1
        self.assertEqual(self.call(DAVE, "finalize", cid, ALICE), "REJECTED")
        self.assertEqual(self.camp(cid)["reserved"], 0)
        with self.assertRaises(Exception):
            self.call(DAVE, "finalize", cid, ALICE)


class TestChallenge(Base):
    def setUp(self):
        super().setUp()
        stub.chain.pages[url_for("revoked")] = "Participant %s was REVOKED for sybil activity" % ALICE

    def challenge(self, cid, who=BOB, url=None, value=2 * WEI, claimant=ALICE):
        return self.call(who, "challenge_claim", cid, claimant, url or url_for("revoked"), value=value)

    def test_upheld_pays_bond_and_bounty_and_releases_rest(self):
        cid = self.eligible_claim()
        self.assertEqual(self.challenge(cid), "CHALLENGED")
        self.assertEqual(self.claim_data(cid, ALICE)["state"], "CHALLENGED")
        self.call(DAVE, "resolve_challenge", cid, ALICE)
        cl = self.claim_data(cid, ALICE)
        self.assertEqual(cl["state"], "REJECTED")
        self.assertEqual(cl["challenge_result"], "UPHELD")
        bounty = 2 * WEI * mod.BOUNTY_BPS // 10000
        self.assertEqual(int(self.h.contract.get_balance(BOB)), 2 * WEI + bounty)
        c = self.camp(cid)
        self.assertEqual(c["reserved"], 0)
        self.assertEqual(c["spent"], bounty)
        self.assertEqual(c["free"], 10 * WEI - bounty)
        self.assertEqual(int(self.h.contract.get_balance(ALICE)), 0)
        self.call(BOB, "withdraw")

    def test_failed_challenge_forfeits_bond_to_claimant(self):
        cid = self.eligible_claim()
        stub.chain.pages[url_for("noise")] = "unrelated page about something else"
        self.challenge(cid, url=url_for("noise"))
        self.call(DAVE, "resolve_challenge", cid, ALICE)
        cl = self.claim_data(cid, ALICE)
        self.assertEqual(cl["state"], "ELIGIBLE_PROPOSED")
        self.assertEqual(cl["challenge_result"], "REJECTED")
        self.assertEqual(int(self.h.contract.get_balance(ALICE)), 2 * WEI)
        self.assertEqual(int(self.h.contract.get_balance(BOB)), 0)
        self.assertEqual(self.call(DAVE, "finalize", cid, ALICE), "PAID")
        self.assertEqual(int(self.h.contract.get_balance(ALICE)), 4 * WEI)

    def test_undetermined_challenge_refunds_challenger(self):
        cid = self.eligible_claim()
        self.challenge(cid)
        self.model.fixed = {"verdict": "UNDETERMINED", "quote": "", "reason": "unclear"}
        self.call(DAVE, "resolve_challenge", cid, ALICE)
        cl = self.claim_data(cid, ALICE)
        self.assertEqual(cl["challenge_result"], "UNDETERMINED_REFUND")
        self.assertEqual(int(self.h.contract.get_balance(BOB)), 2 * WEI)
        self.assertEqual(self.call(DAVE, "finalize", cid, ALICE), "PAID")

    def test_challenge_guards_refund_instead_of_revert(self):
        cid = self.eligible_claim()
        cases = [
            dict(who=ALICE),
            dict(value=1 * WEI),
            dict(value=3 * WEI),
            dict(url="https://evil.example.com/x.txt"),
            dict(claimant=BOB),
        ]
        refunded = 0
        for kw in cases:
            res = self.challenge(cid, **kw)
            self.assertTrue(res.startswith("REJECTED:"), (kw, res))
            refunded += kw.get("value", 2 * WEI)
        self.assertEqual(self.claim_data(cid, ALICE)["state"], "ELIGIBLE_PROPOSED")
        total = int(self.h.contract.get_balance(ALICE)) + int(self.h.contract.get_balance(BOB))
        self.assertEqual(total, refunded)

    def test_unknown_campaign_challenge_refunds(self):
        res = self.call(BOB, "challenge_claim", "c42", ALICE, url_for("revoked"), value=2 * WEI)
        self.assertTrue(res.startswith("REJECTED:"))
        self.assertEqual(int(self.h.contract.get_balance(BOB)), 2 * WEI)

    def test_only_one_challenge_and_window(self):
        cid = self.eligible_claim()
        self.challenge(cid)
        res = self.challenge(cid, who=CAROL)
        self.assertTrue(res.startswith("REJECTED:"))
        cid2 = self.eligible_claim(who=CAROL, cid=cid)
        CLOCK[0] += CHW + 1
        res = self.challenge(cid2, who=BOB, claimant=CAROL)
        self.assertTrue(res.startswith("REJECTED:"))

    def test_cannot_finalize_while_challenged(self):
        cid = self.eligible_claim()
        self.challenge(cid)
        CLOCK[0] += CHW + 10
        with self.assertRaises(Exception):
            self.call(DAVE, "finalize", cid, ALICE)

    def test_resolve_requires_challenged_state(self):
        cid = self.eligible_claim()
        with self.assertRaises(Exception):
            self.call(DAVE, "resolve_challenge", cid, ALICE)

    def test_stale_challenge_cancel_path(self):
        cid = self.eligible_claim()
        self.challenge(cid)
        with self.assertRaises(Exception):
            self.call(DAVE, "cancel_challenge", cid, ALICE)
        CLOCK[0] += mod.EVAL_TIMEOUT + 1
        with self.assertRaises(Exception):
            self.call(DAVE, "resolve_challenge", cid, ALICE)
        self.call(DAVE, "cancel_challenge", cid, ALICE)
        self.assertEqual(int(self.h.contract.get_balance(BOB)), 2 * WEI)
        self.assertEqual(self.call(DAVE, "finalize", cid, ALICE), "PAID")

    def test_challenger_cannot_double_collect(self):
        cid = self.eligible_claim()
        self.challenge(cid)
        self.call(DAVE, "resolve_challenge", cid, ALICE)
        with self.assertRaises(Exception):
            self.call(DAVE, "resolve_challenge", cid, ALICE)
        with self.assertRaises(Exception):
            self.call(DAVE, "cancel_challenge", cid, ALICE)

    def test_sponsor_may_challenge(self):
        cid = self.eligible_claim()
        self.assertEqual(self.challenge(cid, who=SPONSOR), "CHALLENGED")


class TestExpiryAndReclaim(Base):
    def test_expire_claim(self):
        cid = self.create()
        self.claim(ALICE, cid)
        with self.assertRaises(Exception):
            self.call(DAVE, "expire_claim", cid, ALICE)
        CLOCK[0] += mod.EVAL_TIMEOUT + 1
        with self.assertRaises(Exception):
            self.call(DAVE, "evaluate_claim", cid, ALICE)
        self.call(DAVE, "expire_claim", cid, ALICE)
        self.assertEqual(self.claim_data(cid, ALICE)["state"], "REJECTED")
        self.assertEqual(self.camp(cid)["reserved"], 0)

    def test_reclaim_rules(self):
        cid = self.create(gen_budget=11, reward=2)
        self.claim(ALICE, cid)
        with self.assertRaises(Exception):
            self.call(SPONSOR, "reclaim_unused", cid)
        CLOCK[0] += CW + 1
        with self.assertRaises(Exception):
            self.call(ALICE, "reclaim_unused", cid)
        amt = int(self.call(SPONSOR, "reclaim_unused", cid))
        self.assertEqual(amt, 9 * WEI)
        with self.assertRaises(Exception):
            self.call(SPONSOR, "reclaim_unused", cid)
        self.call(DAVE, "evaluate_claim", cid, ALICE)
        CLOCK[0] += CHW + 1
        self.call(DAVE, "finalize", cid, ALICE)
        self.assertEqual(self.camp(cid)["free"], 0)
        with self.assertRaises(Exception):
            self.call(SPONSOR, "reclaim_unused", cid)

    def test_released_slot_becomes_reclaimable(self):
        cid = self.create(gen_budget=4, reward=2)
        stub.chain.pages[url_for("weak")] = page_for(ALICE, ok=False)
        self.call(ALICE, "submit_claim", cid, url_for("weak"))
        self.call(DAVE, "evaluate_claim", cid, ALICE)
        CLOCK[0] += CW + 1
        self.call(DAVE, "finalize", cid, ALICE)
        self.assertEqual(int(self.call(SPONSOR, "reclaim_unused", cid)), 4 * WEI)
        self.call(SPONSOR, "withdraw")
        self.assertEqual(self.h.balance(), 0)


class TestViewsAndAccounting(Base):
    def test_views(self):
        c1 = self.create()
        c2 = self.create(reward=1)
        self.claim(ALICE, c1)
        self.claim(ALICE, c2)
        self.claim(BOB, c1)
        camps = json.loads(self.h.contract.list_campaigns())
        self.assertEqual([c["id"] for c in camps], [c1, c2])
        self.assertEqual(len(json.loads(self.h.contract.list_claims(c1))), 2)
        mine = json.loads(self.h.contract.list_claims_by(ALICE.lower()))
        self.assertEqual(sorted(c["campaign"] for c in mine), sorted([c1, c2]))
        self.assertEqual(self.h.contract.get_claim(c1, CAROL), "")
        stats = json.loads(self.h.contract.get_stats())
        self.assertEqual((stats["campaigns"], stats["claims"]), (2, 3))
        self.assertEqual(json.loads(self.h.contract.get_params())["bond_gen"], mod.BOND_GEN)
        self.assertEqual(self.h.contract.get_balance("0x0000"), "0")
        with self.assertRaises(Exception):
            self.h.contract.get_campaign("nope")

    def test_balance_lookup_is_case_insensitive(self):
        cid = self.eligible_claim()
        CLOCK[0] += CHW + 1
        self.call(DAVE, "finalize", cid, ALICE.upper().replace("0X", "0x"))
        self.assertEqual(int(self.h.contract.get_balance(ALICE.lower())), 2 * WEI)

    def test_full_run_conserves_funds(self):
        stub.chain.pages[url_for("revoked")] = "Participant %s was REVOKED" % BOB
        cid = self.create(gen_budget=12, reward=3)
        for who in (ALICE, BOB, CAROL):
            self.claim(who, cid)
            self.call(DAVE, "evaluate_claim", cid, who)
        self.call(CAROL, "challenge_claim", cid, BOB, url_for("revoked"), value=2 * WEI)
        self.call(DAVE, "resolve_challenge", cid, BOB)
        CLOCK[0] += CW + 1
        self.call(DAVE, "finalize", cid, ALICE)
        self.call(DAVE, "finalize", cid, CAROL)
        self.call(SPONSOR, "reclaim_unused", cid)
        for who in (ALICE, BOB, CAROL, SPONSOR):
            if int(self.h.contract.get_balance(who)) > 0:
                self.call(who, "withdraw")
        self.assertEqual(self.h.balance(), 0)
        paid_out = sum(v for _, v in stub.chain.transfers)
        self.assertEqual(paid_out, 12 * WEI + 2 * WEI)

    def test_withdraw_transfer_uses_value_only(self):
        cid = self.eligible_claim()
        CLOCK[0] += CHW + 1
        self.call(DAVE, "finalize", cid, ALICE)
        self.call(ALICE, "withdraw")
        self.assertEqual(stub.chain.transfers[-1][0], ALICE)


if __name__ == "__main__":
    unittest.main(verbosity=2)
