                                  scenario_idx)
                        # Clear verdict and put back in pending.  Stamp the
                        # last-hook-ts to *now* — not 0 — so the next poll
                        # only re-extracts the verdict after a fresh
                        # idle_prompt event fires (i.e. the scenario has
                        # actually responded to the follow-up).  Popping
                        # the entry instead would accept the stale
                        # idle_prompt left over from the first verdict and
                        # re-trigger verification on the same (still PASS)
                        # transcript turn.
                        state.scenario_verdicts.pop(scenario_idx, None)
                        if scenario_idx in state.verified_scenarios:
                            _log.warning("Scenario %d was in verified_scenarios "
                                         "when flagged — clearing defensively",
                                         scenario_idx)
                            state.verified_scenarios.discard(scenario_idx)
                        _last_scenario_hook_ts[scenario_idx] = time.time()
                        pending.add(scenario_idx)
                        state.latest_output = (
                            f"Scenario {scenario_idx} ({scenario.title}): "
                            f"re-evaluating after verification"
                        )
                        verdicts_changed = True
                        _notify()
                    else:
                        _log.warning("Cannot send follow-up to scenario %d — "
                                     "window gone, marking INPUT_REQUIRED",
                                     scenario_idx)
                        state.scenario_verdicts[scenario_idx] = VERDICT_INPUT_REQUIRED
                        state.latest_output = (
                            f"Scenario {scenario_idx} ({scenario.title}): "
                            f"INPUT_REQUIRED (window gone during verification)"
                        )
                        verdicts_changed = True
                        _notify()

        for scenario in state.scenarios:
            if scenario.index not in pending or not scenario.window_name:
                continue

            pane_id = scenario.pane_id or _get_scenario_pane(session, scenario.window_name)
            if pane_id and not tmux_mod.pane_exists(pane_id):
                pane_id = None
                scenario.pane_id = None
            if pane_id is None:
                retries = retry_counts.get(scenario.index, 0)
                if retries < _SCENARIO_MAX_RETRIES:
                    backoff = _SCENARIO_RETRY_BASE * (2 ** retries)
                    _log.warning(
                        "Scenario %d window died — retry %d/%d "
                        "(backoff %.0fs)",
                        scenario.index, retries + 1,
                        _SCENARIO_MAX_RETRIES, backoff)
                    time.sleep(backoff)
                    retry_counts[scenario.index] = retries + 1
                    if _relaunch_scenario_window(
                        scenario, state, data, pr_data,
                        session, workdir_path,
                    ):
                        # Reset grace period for this retry
                        grace_start = time.monotonic()
                        _last_scenario_hook_ts.pop(scenario.index, None)
                        continue
                    # Relaunch failed — will retry on next poll iteration
                    continue
                _log.warning("Scenario %d window exited without verdict "
                             "(retries exhausted)",
                             scenario.index)
                state.scenario_verdicts[scenario.index] = VERDICT_INPUT_REQUIRED
                pending.discard(scenario.index)
                verdicts_changed = True
                _launch_next_queued()
                continue

            if in_grace:
                continue

            # Hook-driven gate: require a fresh idle_prompt/Stop event
            # before doing any pane work.  Scenarios without a session_id
            # cannot participate in hook-driven polling — mark them
            # INPUT_REQUIRED so they don't silently stall.
            if not scenario.session_id:
                _log.warning("Scenario %d has no session_id — marking INPUT_REQUIRED "
                             "(hook-driven polling requires one)", scenario.index)
                state.scenario_verdicts[scenario.index] = VERDICT_INPUT_REQUIRED
                pending.discard(scenario.index)
                verdicts_changed = True
                _launch_next_queued()
                continue
            ev = _hook_events.read_event(scenario.session_id)
            ev_ts = float((ev or {}).get("timestamp") or 0)
            last_ts = _last_scenario_hook_ts.get(scenario.index, 0.0)
            if ev is None or ev_ts <= last_ts or ev.get("event_type") != "idle_prompt":
                # No new idle_prompt — skip this scenario this tick.
                # Stop fires per-turn (not just at session end); relying
                # on it here would drift from spec R9 and introduce
                # false turn-boundary signals for multi-turn work.
                continue
            _last_scenario_hook_ts[scenario.index] = ev_ts

            # Read verdict straight from the JSONL transcript.  The hook
