"""End-to-end, checkpointed MetaboAnalyst website mapping workflow."""

from __future__ import annotations

import copy
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from config import METABOANALYST_PATHWAY_UPLOAD_URL, deepseek_is_configured
from .ai_matcher import AIMatcher
from .input_validator import (
    InputValidationError,
    validate_input,
    write_standardized_table,
)
from .mapping_clients import KeggPathwayClient, MetaboAnalystMapClient, PubChemSynonymClient
from .networking import choose_network_mode, redact_proxy_url
from .pathway_browser import (
    HumanInterventionRequired,
    PathwayAnalysisBrowser,
    mapping_by_query,
)
from .run_state import (
    RunState,
    read_mapping_csv,
    write_mapping_csv,
    write_goal_coverage,
    write_review_queue,
)
from .research_goal import ResearchGoal
from .scoring import (
    rank_candidates,
    rank_goal_candidates,
    should_auto_confirm,
    should_auto_confirm_goal,
)


@dataclass(frozen=True)
class WorkflowOptions:
    input_path: Path | None
    runs_dir: Path = Path("runs")
    output_dir: Path = Path("output")
    resume: str | None = None
    headless: bool = False
    preflight: bool = True
    review: bool = True
    keep_browser_open: bool = True
    max_items: int | None = None
    browser_channel: str = "chrome"
    browser_network: str = "auto"
    browser_proxy_server: str | None = None
    browser_timeout_ms: int = 120_000
    research_goal: ResearchGoal = ResearchGoal()
    kegg_api_enabled: bool = False


def _resolve_run(options: WorkflowOptions):
    if options.resume:
        state = RunState.load(options.runs_dir, options.resume)
        input_path = Path(state.data["input_path"])
        validation = validate_input(input_path)
        if validation.sha256 != state.data["input_sha256"]:
            raise InputValidationError(
                "input file changed since this run was created; start a new run instead"
            )
        saved_goal = ResearchGoal.from_dict(state.data.get("research_goal"))
        if options.research_goal.active and options.research_goal != saved_goal:
            raise InputValidationError(
                "research goals cannot be changed while resuming; start a new run instead"
            )
        state.data.setdefault("research_goal", saved_goal.as_dict())
        state.save()
        return validation, state, saved_goal
    if options.input_path is None:
        raise InputValidationError("an input file is required for a new run")
    validation = validate_input(options.input_path)
    state = RunState.create(options.runs_dir, validation.path, validation.sha256)
    state.data["input_kind"] = validation.kind
    state.data["research_goal"] = options.research_goal.as_dict()
    state.save()
    state.audit("research_goal_saved", research_goal=options.research_goal.as_dict())
    return validation, state, options.research_goal


def _mapping_snapshot(browser: PathwayAnalysisBrowser, destination: Path) -> list[dict[str, str]]:
    if browser.download_mapping(destination):
        rows = read_mapping_csv(destination)
    else:
        rows = browser.read_mapping_rows()
        write_mapping_csv(destination, rows)
    return rows


def _validate_mapping_coverage(feature_names: tuple[str, ...], rows: list[dict[str, str]]) -> None:
    website_names = [str(row.get("Query", "")).strip() for row in rows]
    if website_names == list(feature_names):
        return
    missing = [name for name in feature_names if name not in set(website_names)]
    if missing:
        sample = ", ".join(missing[:3])
        raise RuntimeError(
            "website mapping does not cover every input feature "
            f"({len(missing)} missing; first: {sample}). A paginated DOM scrape cannot be used as truth."
        )


def _preflight_names(
    state: RunState,
    names: list[str],
    enabled: bool,
    network_mode: str,
    proxy_server: str | None,
) -> dict[str, dict[str, Any]]:
    if state.data.get("preflight"):
        return state.data["preflight"]
    if not enabled:
        return {}
    print(f"Running official mapcompounds preflight for {len(names)} names...")
    try:
        result = MetaboAnalystMapClient(network_mode, proxy_server).map_names(names)
        state.data["preflight"] = result
        state.save()
        state.audit("preflight_complete", result_count=len(result))
        return result
    except Exception as exc:
        state.audit("preflight_failed", error=type(exc).__name__, message=str(exc))
        print(f"Preflight unavailable ({type(exc).__name__}); website workflow will continue.")
        return {}


def _merge_preflight(candidate: dict[str, Any], row: dict[str, Any] | None) -> dict[str, Any]:
    if not row:
        return candidate
    merged = dict(candidate)
    candidate_name = str(candidate.get("name", "")).casefold()
    mapped_name = str(
        row.get("Match") or row.get("match") or row.get("name") or row.get("Name") or ""
    ).casefold()
    if candidate_name and mapped_name and candidate_name != mapped_name:
        return merged
    aliases = {
        "hmdb": ("HMDB", "hmdb", "hmdb_id"),
        "kegg": ("KEGG", "kegg", "kegg_id"),
        "pubchem": ("PubChem", "pubchem", "pubchem_id"),
        "chebi": ("ChEBI", "chebi", "chebi_id"),
        "metlin": ("MetLin", "metlin", "metlin_id"),
    }
    for target, sources in aliases.items():
        if str(merged.get(target, "NA")).upper() != "NA":
            continue
        for source in sources:
            value = row.get(source)
            if value not in (None, "", "NA"):
                merged[target] = str(value)
                break
    return merged


def _enrich_synonyms(
    query: str,
    candidates: list[dict[str, Any]],
    pubchem: PubChemSynonymClient,
    state: RunState,
) -> list[dict[str, Any]]:
    enriched = copy.deepcopy(candidates)
    for candidate in enriched[:3]:
        cid = candidate.get("pubchem")
        candidate["synonyms"] = pubchem.synonyms(cid)
    state.audit(
        "synonym_enrichment",
        query=query,
        candidate_count=len(enriched),
        enriched_count=sum(bool(item.get("synonyms")) for item in enriched),
    )
    return enriched


def _enrich_pathways(
    query: str,
    candidates: list[dict[str, Any]],
    kegg: KeggPathwayClient,
    state: RunState,
) -> list[dict[str, Any]]:
    enriched = copy.deepcopy(candidates)
    for candidate in enriched:
        candidate["pathway_evidence"] = kegg.evidence(candidate.get("kegg"))
    state.data["kegg_cache"] = kegg.cache
    state.save()
    state.audit(
        "kegg_pathway_enrichment",
        query=query,
        linked=sum(
            (candidate.get("pathway_evidence") or {}).get("status") == "linked"
            for candidate in enriched
        ),
        unavailable=sum(
            (candidate.get("pathway_evidence") or {}).get("status") == "unavailable"
            for candidate in enriched
        ),
    )
    return enriched


def _initialize_records(
    state: RunState,
    mapping: list[dict[str, str]],
) -> None:
    changed = False
    for row in mapping:
        query = str(row.get("Query", "")).strip()
        if not query:
            continue
        record = state.records.setdefault(query, {"query": query})
        if row.get("Comment") == "1" and record.get("status") in (None, "pending", "exact"):
            record.update(
                {
                    "status": "exact",
                    "website_before": row,
                    "decision": {
                        "source": "website_exact",
                        "candidate": {
                            "name": row.get("Match", "NA"),
                            "hmdb": row.get("HMDB", "NA"),
                            "kegg": row.get("KEGG", "NA"),
                            "pubchem": row.get("PubChem", "NA"),
                            "chebi": row.get("ChEBI", "NA"),
                            "metlin": row.get("MetLin", "NA"),
                        },
                    },
                    "verified": True,
                }
            )
        else:
            record.setdefault("status", "pending")
            record.setdefault("website_before", row)
        changed = True
    if changed:
        state.save()


def _replay_saved_decisions(
    browser: PathwayAnalysisBrowser,
    state: RunState,
    website_rows: list[dict[str, str]],
) -> None:
    current = mapping_by_query(website_rows)
    replay = [
        record
        for record in state.records.values()
        if record.get("status") in {"auto_applied", "manual_applied"}
        and record.get("verified")
        and (current.get(record["query"], {}).get("Comment") != "1")
    ]
    if not replay:
        return
    print(f"Replaying {len(replay)} previously verified website decisions...")
    for record in replay:
        candidate = record.get("decision", {}).get("candidate")
        if not candidate:
            continue
        result = browser.apply_candidate(record["query"], candidate)
        state.audit("decision_replayed", query=record["query"], result=result)


def _inspect_one(
    query: str,
    browser: PathwayAnalysisBrowser,
    state: RunState,
    ai: AIMatcher,
    pubchem: PubChemSynonymClient,
    kegg: KeggPathwayClient,
    preflight: dict[str, dict[str, Any]],
    research_goal: ResearchGoal,
) -> None:
    print(f"Inspecting View candidates: {query}")
    try:
        candidates = browser.inspect_candidates(query)
    except HumanInterventionRequired as exc:
        print(exc)
        input("Complete the check in Chrome, then press Enter to retry this item... ")
        candidates = browser.inspect_candidates(query)

    candidates = [_merge_preflight(item, preflight.get(query)) for item in candidates]
    if not candidates:
        state.update_record(query, status="no_candidates", candidates=[], verified=False)
        state.audit("no_candidates", query=query)
        return

    enriched = _enrich_synonyms(query, candidates, pubchem, state)
    local_ranked = rank_candidates(query, enriched)
    if research_goal.active:
        local_ranked = _enrich_pathways(query, local_ranked, kegg, state)
    ai_result = ai.judge_candidates(
        query,
        local_ranked,
        research_goal.as_dict() if research_goal.active else None,
    )
    strict_automatic, strict_reason = should_auto_confirm(local_ranked, ai_result)
    if research_goal.active:
        ranked = rank_goal_candidates(query, local_ranked, ai_result, research_goal)
        goal_automatic, goal_reason = should_auto_confirm_goal(
            ranked, ai_result, research_goal
        )
    else:
        ranked = local_ranked
        goal_automatic, goal_reason = False, "no research goal"

    # Synonyms are transient scoring evidence.  Persisting up to 200 values for
    # each of three candidates makes a 1,500-row checkpoint unnecessarily huge
    # and adds no value to the review UI or replay logic.
    for candidate in ranked:
        candidate.pop("synonyms", None)

    if strict_automatic:
        automatic = True
        reason = strict_reason
        decision_source = "automatic"
        selected = next(
            candidate
            for candidate in ranked
            if int(candidate.get("original_rank") or candidate.get("rank") or 0) == 1
        )
    elif goal_automatic:
        automatic = True
        reason = goal_reason
        decision_source = "automatic_goal_priority"
        selected = ranked[0]
    else:
        automatic = False
        reason = goal_reason if research_goal.active else strict_reason
        decision_source = ""

    base = {
        "candidates": ranked,
        "ai": ai_result,
        "auto_policy": {"approved": automatic, "reason": reason},
    }
    if not automatic:
        state.update_record(query, status="queued", verified=False, **base)
        state.audit("queued_for_review", query=query, reason=reason, ai=ai_result)
        return

    # Checkpoint the model/local decision before clicking.  If the website
    # session disappears during the AJAX update, recovery can reuse this exact
    # decision instead of paying for and potentially varying a second AI call.
    decision = {"source": decision_source, "candidate": selected}
    state.update_record(
        query,
        status="auto_ready",
        verified=False,
        decision=decision,
        **base,
    )
    event = (
        "automatic_goal_priority_ready"
        if decision_source == "automatic_goal_priority"
        else "automatic_decision_ready"
    )
    state.audit(
        event,
        query=query,
        decision=decision,
        reason=reason,
        preference_strength=research_goal.strength if research_goal.active else 0,
    )
    _apply_ready_automatic(query, browser, state)


def _apply_ready_automatic(
    query: str,
    browser: PathwayAnalysisBrowser,
    state: RunState,
) -> None:
    record = state.records.get(query) or {}
    candidate = record.get("decision", {}).get("candidate")
    if not candidate:
        raise RuntimeError(f"saved automatic decision for {query!r} has no candidate")
    result = browser.apply_candidate(query, candidate)
    source = str(record.get("decision", {}).get("source") or "automatic")
    decision = {"source": source, "candidate": candidate, "website_result": result}
    state.update_record(
        query,
        status="auto_applied",
        verified=True,
        decision=decision,
    )
    event = (
        "automatic_goal_priority_applied"
        if source == "automatic_goal_priority"
        else "automatic_decision_applied"
    )
    state.audit(event, query=query, decision=decision)


def _upload_input(browser: PathwayAnalysisBrowser, validation) -> None:
    browser.expected_queries = list(validation.feature_names)
    if validation.kind == "mapping":
        browser.upload_compound_list(list(validation.feature_names))
    else:
        browser.upload_concentration_table(validation.path)


def _recover_scan_session(
    browser: PathwayAnalysisBrowser,
    validation,
    state: RunState,
) -> None:
    print("Website operation failed; re-uploading and restoring verified choices...")
    _upload_input(browser, validation)
    restored_rows = browser.read_mapping_rows()
    _validate_mapping_coverage(validation.feature_names, restored_rows)
    _replay_saved_decisions(browser, state, restored_rows)
    state.audit("browser_session_recovered", mapping_rows=len(restored_rows))


def _review_queue(browser: PathwayAnalysisBrowser, state: RunState) -> None:
    queue = [record for record in state.records.values() if record.get("status") == "queued"]
    if not queue:
        return
    print(f"\nConcentrated review: {len(queue)} items")
    for position, record in enumerate(queue, start=1):
        query = record["query"]
        candidates = record.get("candidates") or []
        ai = record.get("ai") or {}
        print(f"\n[{position}/{len(queue)}] {query}")
        for index, candidate in enumerate(candidates, start=1):
            evidence = candidate.get("pathway_evidence") or {}
            linked = "; ".join(
                str(item.get("name") or item.get("id") or "")
                for item in evidence.get("pathways") or []
            )
            print(
                f"  {index}. {candidate.get('name')}  "
                f"score={candidate.get('local_score', 0):.3f} "
                f"goal={float(candidate.get('goal_score', 0)):.3f} "
                f"target={float(candidate.get('target_alignment', 0)):.2f} "
                f"HMDB={candidate.get('hmdb', 'NA')} "
                f"PubChem={candidate.get('pubchem', 'NA')} "
                f"KEGG-status={evidence.get('status', 'not-checked')}"
            )
            if linked:
                print(f"     pathways: {linked}")
            if candidate.get("target_reason"):
                print(f"     target reason: {candidate['target_reason']}")
            if candidate.get("structural_conflicts"):
                print(f"     WARNING: {'; '.join(candidate['structural_conflicts'])}")
        print(
            f"  AI: candidate {ai.get('selected_index', 0)}, "
            f"confidence={float(ai.get('confidence', 0)):.2f}; {ai.get('reasoning', '')}"
        )
        while True:
            answer = input("Choose a candidate number, or s to skip: ").strip().casefold()
            if answer in {"s", "skip", ""}:
                state.update_record(query, status="skipped", verified=False)
                state.audit("manual_review_skipped", query=query)
                break
            if answer.isdigit() and 1 <= int(answer) <= len(candidates):
                selected = candidates[int(answer) - 1]
                result = browser.apply_candidate(query, selected)
                decision = {"source": "manual", "candidate": selected, "website_result": result}
                state.update_record(
                    query,
                    status="manual_applied",
                    verified=True,
                    decision=decision,
                )
                state.audit("manual_decision_applied", query=query, decision=decision)
                break
            print("Invalid choice.")


def _write_outputs(
    validation,
    browser: PathwayAnalysisBrowser,
    state: RunState,
    research_goal: ResearchGoal,
) -> None:
    website_final_path = (
        state.paths.root / "mapping_website_final.csv"
        if validation.kind == "mapping"
        else state.paths.mapping_final
    )
    final_rows = _mapping_snapshot(browser, website_final_path)
    confirmed: dict[str, str] = {}
    for query, record in state.records.items():
        if not record.get("verified"):
            continue
        candidate = record.get("decision", {}).get("candidate", {})
        name = str(candidate.get("name") or "").strip()
        if name and name.upper() != "NA":
            confirmed[query] = name
    if validation.kind == "mapping":
        website_by_query = mapping_by_query(final_rows)
        merged_rows = []
        for original in validation.source_mapping:
            query = str(original.get("Query") or "").strip()
            website_row = website_by_query.get(query)
            merged_rows.append(website_row if website_row and website_row.get("Comment") == "1" else original)
        write_mapping_csv(state.paths.mapping_final, merged_rows)
    else:
        write_standardized_table(validation.path, state.paths.standardized, confirmed)
    outstanding = [
        record
        for record in state.records.values()
        if record.get("status") in {"queued", "skipped", "no_candidates", "error"}
    ]
    write_review_queue(state.paths.review_queue, outstanding)
    coverage_records = list(state.records.values())
    if validation.kind == "mapping":
        # The browser upload contains only Comment=0 rows. Include original exact
        # rows so an explicitly requested compound is not incorrectly reported
        # as absent merely because it never needed View processing.
        cache = state.data.get("kegg_cache") or {}
        for row in validation.source_mapping:
            if str(row.get("Comment") or "").strip() != "1":
                continue
            kegg_ids = KeggPathwayClient.compound_ids(row.get("KEGG"))
            cache_key = "+".join(value.upper() for value in kegg_ids)
            evidence = cache.get(cache_key) if cache_key else None
            if not evidence:
                evidence = {
                    "status": "id_only" if kegg_ids else "no_kegg",
                    "kegg_ids": kegg_ids,
                    "pathways": [],
                    "error": "",
                }
            coverage_records.append(
                {
                    "query": str(row.get("Query") or ""),
                    "status": "exact",
                    "verified": True,
                    "decision": {
                        "source": "website_exact",
                        "candidate": {
                            "name": row.get("Match", "NA"),
                            "kegg": row.get("KEGG", "NA"),
                            "hmdb": row.get("HMDB", "NA"),
                            "pubchem": row.get("PubChem", "NA"),
                            "pathway_evidence": evidence,
                        },
                    },
                }
            )
    write_goal_coverage(
        state.paths.goal_coverage,
        research_goal.as_dict(),
        coverage_records,
    )
    state.audit(
        "outputs_written",
        mapping_rows=len(final_rows),
        standardized_names=len(confirmed),
        review_items=len(outstanding),
        research_goal=research_goal.as_dict(),
    )


def _publish_outputs(validation, state: RunState, output_dir: Path) -> dict[str, str]:
    """Publish the files an operator needs, separate from run checkpoints."""

    destination = output_dir.expanduser().resolve() / state.data["run_id"]
    destination.mkdir(parents=True, exist_ok=True)
    if validation.kind == "mapping":
        processed_source = state.paths.mapping_final
        processed_name = f"{validation.path.stem}_processed.csv"
    else:
        processed_source = state.paths.standardized
        processed_name = f"{validation.path.stem}_standardized.csv"

    processed_destination = destination / processed_name
    review_destination = destination / "review_queue.csv"
    goal_destination = destination / "goal_coverage.csv"
    explanation_destination = destination / "matching_explanation.txt"
    if not state.paths.goal_coverage.is_file():
        write_goal_coverage(
            state.paths.goal_coverage,
            state.data.get("research_goal") or {},
            state.records.values(),
        )
    shutil.copy2(processed_source, processed_destination)
    shutil.copy2(state.paths.review_queue, review_destination)
    shutil.copy2(state.paths.goal_coverage, goal_destination)
    goal = ResearchGoal.from_dict(state.data.get("research_goal"))
    explanation_destination.write_text(
        "MetaboAnalyst AI 匹配结果说明\n"
        "================================\n\n"
        f"本次客户偏好尺度（PreferenceStrength）：{goal.strength}/100\n"
        "0 表示完全按化学身份严格匹配；50 表示身份与研究目标并重；100 表示最大程度按客户希望的物质、类别和通路自动选择，并允许 AI 在缺少 KEGG 关联或存在结构警告时继续自动处理。\n\n"
        "AIConfidence：AI 在网站给出的候选中作出本次选择的确定程度。\n"
        "IdentityConfidence：候选与原 Query 属于同一化学实体的可能程度。\n"
        "TargetAlignment：候选与客户目标物质、类别或通路的符合程度。\n"
        "GoalScore：按照本次偏好尺度合并名称、身份、目标和通路证据后的排序分数。\n"
        "KEGG pathway evidence：linked 表示已查询到具体通路；id_only 表示 MetaboAnalyst 候选带有 KEGG ID，但未在线验证具体通路。\n\n"
        "上述数值用于解释名称映射决策，不是实验概率、p 值，也不能单独证明某条生物通路已被激活。"
        "Pathway Analysis 本身仍属于基于数据库覆盖和模型的推测性分析。\n",
        encoding="utf-8",
    )
    published = {
        "processed": str(processed_destination),
        "review_queue": str(review_destination),
        "goal_coverage": str(goal_destination),
        "explanation": str(explanation_destination),
    }
    state.data["published_outputs"] = published
    state.save()
    state.audit("outputs_published", **published)
    return published


def run_workflow(options: WorkflowOptions) -> RunState:
    validation, state, research_goal = _resolve_run(options)
    print(f"Run: {state.data['run_id']}")
    print(f"Input: {validation.path}")
    if validation.kind == "mapping":
        print(f"Unmatched queries to upload: {len(validation.feature_names)}")
    else:
        print(f"Features: {len(validation.feature_names)}; Samples: {len(validation.sample_names)}")
    print(f"Research goal: {research_goal.describe()}")

    mode, probes = choose_network_mode(
        METABOANALYST_PATHWAY_UPLOAD_URL,
        options.browser_network,
        options.browser_proxy_server,
    )
    state.data["network"] = {
        "requested": options.browser_network,
        "selected": mode,
        "proxy": redact_proxy_url(options.browser_proxy_server),
        "probes": [probe.as_dict() for probe in probes],
    }
    state.save()
    for probe in probes:
        print(
            f"Network probe ({probe.mode}): "
            f"{'reachable' if probe.reachable else 'failed'} in {probe.elapsed_ms} ms"
        )
    if not any(probe.reachable for probe in probes):
        print(
            "Direct and system routes both failed. If the VPN uses a TUN/full-tunnel mode, "
            "add *.metaboanalyst.ca and *.xialab.ca to the VPN direct/bypass list."
        )

    preflight = _preflight_names(
        state,
        list(validation.feature_names),
        options.preflight,
        mode,
        options.browser_proxy_server,
    )
    ai = AIMatcher()
    if not deepseek_is_configured():
        print("DEEPSEEK_API_KEY is not set; non-exact candidates will be written to the review queue.")
    pubchem = PubChemSynonymClient(mode, options.browser_proxy_server)
    kegg_api_enabled = options.kegg_api_enabled or bool(state.data.get("kegg_api_enabled"))
    kegg = KeggPathwayClient(
        mode,
        options.browser_proxy_server,
        cache=state.data.setdefault("kegg_cache", {}),
        enabled=kegg_api_enabled,
    )
    state.data["kegg_api_enabled"] = kegg_api_enabled
    state.save()

    browser = PathwayAnalysisBrowser(
        headless=options.headless,
        browser_channel=options.browser_channel,
        network_mode=mode,
        proxy_server=options.browser_proxy_server,
        timeout_ms=options.browser_timeout_ms,
    ).start()
    try:
        state.set_stage("uploading")
        _upload_input(browser, validation)
        state.set_stage("name_check")

        before_rows = _mapping_snapshot(browser, state.paths.mapping_before)
        _validate_mapping_coverage(validation.feature_names, before_rows)
        _initialize_records(state, before_rows)
        _replay_saved_decisions(browser, state, before_rows)

        website = mapping_by_query(before_rows)
        pending = [
            name
            for name in validation.feature_names
            if website.get(name, {}).get("Comment") == "0"
            and state.records.get(name, {}).get("status")
            not in {"auto_applied", "manual_applied", "queued", "skipped", "no_candidates"}
        ]
        if options.max_items is not None:
            pending = pending[: options.max_items]
        state.set_stage("scanning")
        for index, query in enumerate(pending, start=1):
            print(f"[{index}/{len(pending)}]", end=" ")

            def process_current() -> None:
                if state.records.get(query, {}).get("status") == "auto_ready":
                    print(f"Applying checkpointed automatic decision: {query}")
                    _apply_ready_automatic(query, browser, state)
                else:
                    _inspect_one(
                        query,
                        browser,
                        state,
                        ai,
                        pubchem,
                        kegg,
                        preflight,
                        research_goal,
                    )

            try:
                process_current()
            except Exception as first_exc:
                state.audit(
                    "item_retry_started",
                    query=query,
                    error=type(first_exc).__name__,
                    message=str(first_exc),
                )
                try:
                    _recover_scan_session(browser, validation, state)
                    process_current()
                    state.audit("item_retry_succeeded", query=query)
                    continue
                except Exception as exc:
                    record = state.records.get(query, {})
                    retry_status = (
                        "auto_ready"
                        if str(record.get("decision", {}).get("source") or "").startswith(
                            "automatic"
                        )
                        and not record.get("verified")
                        else "error"
                    )
                    state.update_record(
                        query,
                        status=retry_status,
                        verified=False,
                        error={"type": type(exc).__name__, "message": str(exc)},
                    )
                    state.audit(
                        "item_failed",
                        query=query,
                        error=type(exc).__name__,
                        message=str(exc),
                        first_error=type(first_exc).__name__,
                    )
                    if options.keep_browser_open:
                        print(
                            "The retry also failed. Chrome will remain open so the page can be inspected."
                        )
                        browser.keep_open_for_operator()
                    raise

        write_review_queue(
            state.paths.review_queue,
            [record for record in state.records.values() if record.get("status") == "queued"],
        )
        if options.review:
            state.set_stage("review")
            _review_queue(browser, state)

        state.set_stage("writing_outputs")
        _write_outputs(validation, browser, state, research_goal)
        published = _publish_outputs(validation, state, options.output_dir)
        state.set_stage("complete")
        print(f"Completed. Artifacts: {state.paths.root}")
        print(f"Processed file: {published['processed']}")
        print(f"Review queue: {published['review_queue']}")
        print(f"Goal coverage: {published['goal_coverage']}")
        print("The workflow has intentionally stopped at Name check.")
        if options.keep_browser_open:
            browser.keep_open_for_operator()
        return state
    finally:
        browser.close()
