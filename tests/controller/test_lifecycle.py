"""D45: explicit instance lifecycle in the controller (state.py ModelState) and event-ended swap reservations.

- the GPU schedulers' events move ACTIVATING -> ACTIVE and DEACTIVATING -> INACTIVE, only for the matching transition;
- the policies see the same two states as before (ACTIVATING = active, DEACTIVATING = inactive): same actions;
- the edf/lvf rotation cap counts what it counted before (an ACTIVATING model is no longer in flight);
- residency counts from the load; the impasse detector counts loads (ACTIVATING) but not victims leaving;
- reservations (PRISM_SWAP_RESERVATION_END=event) end on activation / no waiting requests / 120 s, not after 15 s.

Run: /mnt/scratch/scheduler/opt-env/bin/python -m unittest tests/controller/test_lifecycle.py
"""
import json
import os
import sys
import tempfile
import time
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from test_decision_log import FREE_GB, WEIGHTS, mqt, scenario, sg, st  # noqa: E402  (SGLang stubbed out)

S = st.ModelState
WEIGHTS4 = {f"model_{i}": {"model_size": 15.0, "cell_size": 131072} for i in range(1, 5)}
MEM = types.SimpleNamespace(model_weights_memory=15.0, memory_pool_memory=1.0, total_used_memory=16.0,
                            req_to_token_pool_memory=0.0, token_to_kv_pool_memory=1.0)


def inst(name, state, gpu=0):
    return st.ModelInstanceState(model_name=name, model_path="p", instance_idx=0, gpu_ids=[gpu], state=state,
                                 memory_usage=MEM, init_memory_pool_size=6.0)


def clean_env(**env):
    for k in list(os.environ):
        if k.startswith("PRISM_"):
            del os.environ[k]
    os.environ.update(env)


def policy(eviction="idle", free_gb=FREE_GB, weights=WEIGHTS, **env):
    clean_env(PRISM_EVICTION=eviction, PRISM_IDLE_THRESHOLD="50", **env)
    sg.get_available_gpu_memory = lambda device, gpu_id: free_gb
    return sg.SimpleGlobalPolicy(num_gpus=1, gpu_mem=140.0, model_weights_info=weights, workers_per_gpu=4)


def rotation_state(now):
    """model_1..3 active and busy, model_4 inactive with 2 waiting requests (as tests/policy/test_deadline.py)."""
    insts, queues = {}, {}
    for i in range(1, 5):
        name = f"model_{i}"
        insts[name] = [inst(name, S.ACTIVE if i <= 3 else S.INACTIVE)]
        q = queues[name] = mqt.ModelQueueTracker(name)
        q._last_arrival_time = now - 0.5
        if i <= 3:
            q.running_reqs.append(mqt.Req(rid=f"r{i}", arrival_time=now - 0.5, slo=7.0, model=name, prompt_len=500,
                                          output_len=300, state=mqt.ReqState.RUNNING))
        else:
            for k in range(2):
                q.waiting_reqs.append(mqt.Req(rid=f"w{k}", arrival_time=now - 2 + k, slo=7.0, model=name,
                                              prompt_len=500, output_len=300))
    return queues, insts


def rotate(p, now):
    """One edf cycle that evicts a victim for model_4 (2 GB free: it does not fit)."""
    p.first_request_time = now - 300
    queues, insts = rotation_state(now)
    for i in range(1, 4):
        p.active_since[f"model_{i}"] = now - 100 * i
    actions = p.gen_actions(queues, insts)
    return queues, insts, actions


class TransitionsTest(unittest.TestCase):
    def test_activation_and_deactivation_follow_the_events(self):
        i = inst("m", S.INACTIVE)
        i.on_activating(MEM, gpu_id=1)
        self.assertEqual((i.state, i.gpu_ids, i.serving), (S.ACTIVATING, [1], True))
        self.assertEqual(st.apply_lifecycle_event([i], {"event": "model_activated", "gpu_id": 0}), [])  # other GPU
        self.assertEqual(st.apply_lifecycle_event([i], {"event": "model_deactivated", "gpu_id": 1}), [])  # stale
        self.assertEqual(st.apply_lifecycle_event([i], {"event": "model_activated", "gpu_id": 1}), [i])
        self.assertEqual((i.state, i.serving), (S.ACTIVE, True))
        i.on_deactivating(MEM)
        self.assertEqual((i.state, i.serving), (S.DEACTIVATING, False))
        self.assertEqual(st.apply_lifecycle_event([i], {"event": "model_activated", "gpu_id": 1}), [])
        self.assertEqual(st.apply_lifecycle_event([i], {"event": "model_deactivated", "gpu_id": 1}), [i])
        self.assertEqual(i.state, S.INACTIVE)

    def test_reactivated_while_leaving_ignores_the_late_deactivation(self):
        i = inst("m", S.ACTIVE)
        i.on_deactivating(MEM)
        i.on_activating(MEM, gpu_id=0)  # the policy activates it again before the deactivation is reported
        st.apply_lifecycle_event([i], {"event": "model_deactivated", "gpu_id": 0})
        self.assertEqual(i.state, S.ACTIVATING)

    def test_lost_from_any_transition(self):
        for state in (S.ACTIVATING, S.ACTIVE, S.DEACTIVATING):
            i = inst("m", state)
            st.apply_lifecycle_event([i], {"event": "model_lost", "gpu_id": 0, "reason": "x"})
            self.assertEqual(i.state, S.INACTIVE)

    def test_transition_without_event_is_reported_not_assumed(self):
        """D59: a missing confirmation is not a success; the instance keeps its state for the controller to act."""
        a, d, ok = inst("a", S.INACTIVE), inst("d", S.ACTIVE), inst("k", S.INACTIVE)
        a.on_activating(MEM)
        d.on_deactivating(MEM)
        ok.on_activating(MEM)
        a.state_since = d.state_since = 100.0
        ok.state_since = 200.0
        expired = st.expired_transitions({"a": [a], "d": [d], "k": [ok]}, now=221.0, timeout_s=120.0)
        self.assertEqual((a.state, d.state, ok.state), (S.ACTIVATING, S.DEACTIVATING, S.ACTIVATING))
        self.assertEqual(sorted(i.model_name for i in expired), ["a", "d"])


class CommandRidTest(unittest.TestCase):
    """D59: an event moves an instance only if it answers the instance's current command."""

    def test_late_activation_does_not_confirm_a_newer_one(self):
        i = inst("m", S.INACTIVE)
        i.on_activating(MEM, gpu_id=0, cmd_rid="a1")
        i.on_deactivating(MEM, cmd_rid="d1")  # evicted while loading
        i.on_activating(MEM, gpu_id=0, cmd_rid="a2")  # and activated again
        late = {"event": "model_activated", "gpu_id": 0, "rid": "a1"}
        self.assertTrue(st.is_stale_event([i], late))
        self.assertEqual(st.apply_lifecycle_event([i], late), [])
        self.assertEqual(i.state, S.ACTIVATING)
        current = {"event": "model_activated", "gpu_id": 0, "rid": "a2"}
        self.assertFalse(st.is_stale_event([i], current))
        self.assertEqual(st.apply_lifecycle_event([i], current), [i])
        self.assertEqual(i.state, S.ACTIVE)

    def test_late_loss_does_not_drop_a_newer_activation(self):
        i = inst("m", S.INACTIVE)
        i.on_activating(MEM, gpu_id=0, cmd_rid="a1")
        i.on_deactivating(MEM, cmd_rid="d1")
        i.on_activating(MEM, gpu_id=0, cmd_rid="a2")
        st.apply_lifecycle_event([i], {"event": "model_lost", "gpu_id": 0, "rid": "a1", "reason": "activation failed"})
        self.assertEqual(i.state, S.ACTIVATING)
        st.apply_lifecycle_event([i], {"event": "model_lost", "gpu_id": 0, "rid": "a2", "reason": "worker died"})
        self.assertEqual(i.state, S.INACTIVE)

    def test_without_rid_as_before(self):
        """Initial placement (no command sent yet) and events without rid behave as before D59."""
        i = inst("m", S.ACTIVE)  # cmd_rid None
        st.apply_lifecycle_event([i], {"event": "model_lost", "gpu_id": 0, "rid": "init", "reason": "worker died"})
        self.assertEqual(i.state, S.INACTIVE)
        j = inst("m", S.INACTIVE)
        j.on_activating(MEM, gpu_id=0, cmd_rid="a1")
        st.apply_lifecycle_event([j], {"event": "model_activated", "gpu_id": 0})
        self.assertEqual(j.state, S.ACTIVE)

    def test_stale_only_on_the_event_gpu(self):
        i0, i1 = inst("m", S.INACTIVE, gpu=0), inst("m", S.INACTIVE, gpu=1)
        i0.on_activating(MEM, gpu_id=0, cmd_rid="a0")
        i1.on_activating(MEM, gpu_id=1, cmd_rid="a1")
        self.assertTrue(st.is_stale_event([i0, i1], {"event": "model_activated", "gpu_id": 0, "rid": "a1"}))
        self.assertFalse(st.is_stale_event([i0, i1], {"event": "model_activated", "gpu_id": 1, "rid": "a1"}))

    def test_actions_carry_distinct_rids(self):
        from sglang.multi_model.scheduling import action
        a, b = action.ActivateAction(model_name="m", gpu_id=0), action.DeactivateAction(model_name="m", gpu_id=0)
        self.assertNotEqual(a.rid, b.rid)
        self.assertEqual(a.to_dict()["rid"], a.rid)  # sent to /activate, echoed by the GPU scheduler


class SameDecisionsTest(unittest.TestCase):
    """The policy's actions do not depend on whether a model is still loading or still leaving."""

    def tearDown(self):
        clean_env()

    def actions(self, change):
        p = policy()
        now = time.time()
        p.first_request_time = now - 200
        queues, insts = scenario(now)
        change(insts)
        return [(type(a).__name__, a.model_name) for a in p.gen_actions(queues, insts)]

    def test_activating_is_active_and_deactivating_is_inactive(self):
        base = self.actions(lambda insts: None)
        self.assertIn(("ActivateAction", "model_3"), base)
        self.assertIn(("DeactivateAction", "model_1"), base)
        for name, state in (("model_1", S.ACTIVATING), ("model_2", S.ACTIVATING), ("model_3", S.DEACTIVATING)):
            self.assertEqual(self.actions(lambda insts: setattr(insts[name][0], "state", state)), base, (name, state))


class RotationCapTest(unittest.TestCase):
    def tearDown(self):
        clean_env()

    def snapshot(self, p, insts, queues, now):
        g2a = p._get_gpu_to_active_instances(insts)
        return p._deadline_snapshot(queues, insts, g2a, set(), {0: 2.0}, now)

    def test_loading_model_is_not_a_rotation_in_flight(self):
        p = policy("edf", 2.0, WEIGHTS4)
        now = time.time()
        queues, insts, actions = rotate(p, now)
        self.assertEqual([a.model_name for a in actions], ["model_3"])  # victim for model_4
        self.assertEqual(self.snapshot(p, insts, queues, now + 1).in_flight, 1)  # victim leaving
        insts["model_4"][0].on_activating(MEM, gpu_id=0)  # its activation was sent: as before D45, done
        self.assertEqual(self.snapshot(p, insts, queues, now + 2).in_flight, 0)


class ResidencyTest(unittest.TestCase):
    def tearDown(self):
        clean_env()

    def test_residency_starts_when_loaded(self):
        p = policy()
        t0 = time.time()
        p.first_request_time = t0 - 200
        queues, insts = scenario(t0)
        insts["model_2"][0].on_activating(MEM, gpu_id=0)
        p.active_since["model_2"] = t0 - 500  # whatever it was: loading restarts it
        p.gen_actions(queues, insts)
        loading = p.active_since["model_2"]
        self.assertGreaterEqual(loading, t0)
        insts["model_2"][0].on_activated()
        loaded_at = insts["model_2"][0].state_since
        p.gen_actions(queues, insts)
        self.assertEqual(p.active_since["model_2"], loaded_at)
        p.gen_actions(queues, insts)
        self.assertEqual(p.active_since["model_2"], loaded_at)  # then it stays


class ReservationTest(unittest.TestCase):
    def tearDown(self):
        clean_env()

    def test_event_mode_outlives_the_old_15_s_until_activation(self):
        p = policy("edf", 2.0, WEIGHTS4)
        now = time.time()
        queues, insts, _ = rotate(p, now)
        self.assertTrue(p._reserved("model_4", now + 20))  # the victim may take ~20 s to leave
        p._end_reservations(now + 20, {"model_1", "model_2"}, queues)
        self.assertTrue(p._reserved("model_4", now + 20))
        p._end_reservations(now + 21, {"model_1", "model_2", "model_4"}, queues)  # activation sent
        self.assertFalse(p._reserved("model_4", now + 21))

    def test_event_mode_drops_it_without_waiting_requests(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "decisions.jsonl")
            p = policy("edf", 2.0, WEIGHTS4, PRISM_DECISION_LOG=path)
            now = time.time()
            queues, insts, _ = rotate(p, now)
            queues["model_4"].waiting_reqs.clear()
            p.dlog.begin(now + 3)
            p._end_reservations(now + 3, {"model_1", "model_2"}, queues)
            p.dlog.end()
            p.dlog._f.close()
            with open(path) as f:
                notes = [n for line in f for n in json.loads(line)["notes"]]
        self.assertFalse(p._reserved("model_4", now + 3))
        self.assertIn("reservation_dropped", [n["kind"] for n in notes])

    def test_event_mode_safety_bound(self):
        p = policy("edf", 2.0, WEIGHTS4, PRISM_SWAP_RESERVATION_MAX_S="60")
        now = time.time()
        queues, insts, _ = rotate(p, now)
        self.assertTrue(p._reserved("model_4", now + 59))
        self.assertFalse(p._reserved("model_4", now + 61))

    def test_timer_mode_is_the_old_15_s(self):
        p = policy("edf", 2.0, WEIGHTS4, PRISM_SWAP_RESERVATION_END="timer")
        now = time.time()
        queues, insts, _ = rotate(p, now)
        p._end_reservations(now + 1, {"model_1", "model_2", "model_4"}, queues)  # untouched in timer mode
        self.assertTrue(p._reserved("model_4", now + 14))
        self.assertFalse(p._reserved("model_4", now + 16))

    def test_no_new_rotation_for_a_reserved_model(self):
        p = policy("edf", 2.0, WEIGHTS4, PRISM_EDF_BUDGET="3")  # the budget alone would allow another one
        now = time.time()
        queues, insts, actions = rotate(p, now)
        self.assertEqual(len(actions), 1)
        p.pressure_cooldown_until.clear()  # the 10 s cooldown has passed
        insts["model_3"][0].on_deactivating(MEM)  # the victim is still leaving
        snap = p._deadline_snapshot(queues, insts, p._get_gpu_to_active_instances(insts), set(), {0: 2.0}, now + 30)
        self.assertTrue(snap.models["model_4"].cooldown)


class DeadlockTransitionsTest(unittest.TestCase):
    def tearDown(self):
        clean_env()

    def stalled_after_two_cycles(self, other_state):
        p = policy(PRISM_DEADLOCK_S="1000")
        now = time.time()
        queues, insts = scenario(now)
        queues["model_2"].waiting_reqs.append(mqt.Req(rid="x", arrival_time=now - 1, slo=1.0, model="model_2",
                                                      prompt_len=10, output_len=10))
        insts["model_3"][0].state = other_state
        g2a = p._get_gpu_to_active_instances(insts)
        p._deadlock_check(queues, insts, g2a, set(), False)
        p._deadlock_check(queues, insts, g2a, set(), False)
        return p.deadlock.since is not None

    def test_loads_pause_the_clock_leaving_victims_do_not(self):
        self.assertTrue(self.stalled_after_two_cycles(S.INACTIVE))
        self.assertTrue(self.stalled_after_two_cycles(S.DEACTIVATING))  # as before D45
        self.assertFalse(self.stalled_after_two_cycles(S.ACTIVATING))


if __name__ == "__main__":
    unittest.main()
