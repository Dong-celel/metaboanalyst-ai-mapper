"""MetaboAnalyst Pathway Analysis name-mapping automation CLI."""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

from modules.input_validator import InputValidationError, validate_input
from modules.research_goal import ResearchGoal, parse_goal_line
from modules.workflow import WorkflowOptions, run_workflow


def _configure_console() -> None:
    """Keep Chinese paths and compound names printable on Windows consoles."""

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def _discover_input(input_dir: Path) -> Path:
    """Return the only CSV/TXT in the drop folder, never guess among several."""

    directory = input_dir.expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    files = sorted(
        path
        for path in directory.iterdir()
        if path.is_file() and path.suffix.casefold() in {".csv", ".txt"}
    )
    if not files:
        raise InputValidationError(
            f"no .csv or .txt input file found in {directory}; place one file there first"
        )
    if len(files) > 1:
        names = ", ".join(path.name for path in files)
        raise InputValidationError(
            f"multiple input files found in {directory}: {names}; "
            "keep one file or pass its path explicitly"
        )
    return files[0]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="metaboanalyst-mapper",
        description=(
            "Upload a name_map.csv or concentration table to MetaboAnalyst Pathway Analysis, "
            "inspect Name check results, and safely resolve high-confidence candidates."
        ),
    )
    parser.add_argument("--version", action="version", version="MetaboAnalyst Mapper 1.0.0")
    commands = parser.add_subparsers(dest="command", required=True)

    run = commands.add_parser("run", help="run the website-assisted mapping workflow")
    run.add_argument(
        "input",
        type=Path,
        nargs="?",
        help="MetaboAnalyst name_map.csv or a concentration CSV file",
    )
    run.add_argument(
        "--resume",
        metavar="RUN_ID_OR_PATH",
        help="resume a run from runs/<id> or from an explicit run directory",
    )
    run.add_argument("--runs-dir", type=Path, default=Path("runs"))
    run.add_argument(
        "--input-dir",
        type=Path,
        default=Path("input"),
        help="folder auto-scanned when INPUT is omitted; default: input",
    )
    run.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output"),
        help="folder receiving processed files; default: output",
    )
    run.add_argument("--headless", action="store_true", help="hide the browser (not recommended)")
    run.add_argument("--no-preflight", action="store_true", help="skip the public mapcompounds preflight")
    run.add_argument("--no-review", action="store_true", help="write the review queue without prompting")
    run.add_argument(
        "--ask-deepseek-key",
        action="store_true",
        help="securely prompt for a DeepSeek key for this process only",
    )
    run.add_argument(
        "--ask-research-goal",
        action="store_true",
        help="prompt once for target compounds, compound classes, and pathways",
    )
    run.add_argument(
        "--target-compound",
        action="append",
        default=[],
        help="desired compound; repeat this option for multiple compounds",
    )
    run.add_argument(
        "--target-class",
        action="append",
        default=[],
        help="desired compound class; repeat this option for multiple classes",
    )
    run.add_argument(
        "--target-pathway",
        action="append",
        default=[],
        help="desired pathway; repeat this option for multiple pathways",
    )
    run.add_argument(
        "--preference-strength",
        type=int,
        default=80,
        metavar="0-100",
        help="0=strict identity matching, 100=maximum goal-oriented automation; default: 80",
    )
    run.add_argument(
        "--enable-kegg-api",
        action="store_true",
        help="query KEGG pathway links; enable only when your use is covered by an appropriate KEGG license",
    )
    run.add_argument("--close-browser", action="store_true", help="close Chrome immediately when finished")
    run.add_argument(
        "--max-items",
        type=int,
        default=None,
        help="inspect at most this many unmatched items (useful for a small live regression)",
    )
    run.add_argument(
        "--browser-channel",
        default="chrome",
        help="Playwright browser channel; default: chrome",
    )
    run.add_argument(
        "--browser-network",
        choices=("auto", "direct", "system", "custom"),
        default="auto",
        help="MetaboAnalyst route; auto probes direct first to avoid VPN timeouts",
    )
    run.add_argument(
        "--browser-proxy-server",
        default=None,
        help="proxy URL used only with --browser-network custom",
    )
    run.add_argument(
        "--browser-timeout",
        type=int,
        default=120,
        metavar="SECONDS",
        help="maximum wait for each website transition; default: 120",
    )

    validate = commands.add_parser("validate", help="validate a mapping or concentration CSV without uploading it")
    validate.add_argument("input", type=Path)
    return parser


def _validate_only(path: Path) -> int:
    result = validate_input(path)
    print("Validation passed")
    print(f"  Input kind: {result.kind}")
    print(f"  Features: {len(result.feature_names)}")
    if result.kind == "concentration":
        print(f"  Samples:  {len(result.sample_names)}")
        print(f"  Groups:   {', '.join(result.groups)}")
    print(f"  SHA-256:  {result.sha256}")
    return 0


def _prompt_research_goal(initial: ResearchGoal) -> ResearchGoal:
    print("\nOptional research goals (use semicolons between items; commas are preserved).")
    print("Leave all three lines empty to use standard conservative matching.")

    def ask(label: str, current: tuple[str, ...]) -> tuple[str, ...]:
        default = "; ".join(current)
        suffix = f" [{default}]" if default else ""
        entered = input(f"{label}{suffix}: ").strip()
        return parse_goal_line(entered) if entered else current

    compounds = ask("Target compounds", initial.compounds)
    classes = ask("Target compound classes", initial.classes)
    pathways = ask("Target pathways", initial.pathways)
    strength = initial.strength
    if compounds or classes or pathways:
        print("Preference scale: 0=strict identity, 50=balanced, 100=maximum goal preference.")
        entered = input(f"Preference strength 0-100 [{strength}]: ").strip()
        if entered:
            try:
                strength = int(entered)
            except ValueError as exc:
                raise InputValidationError("preference strength must be an integer from 0 to 100") from exc
    try:
        return ResearchGoal.create(compounds, classes, pathways, strength)
    except ValueError as exc:
        raise InputValidationError(str(exc)) from exc


def main(argv: list[str] | None = None) -> int:
    _configure_console()
    args = build_parser().parse_args(argv)
    try:
        if args.command == "validate":
            return _validate_only(args.input)

        input_path = args.input
        if not args.resume and input_path is None:
            input_path = _discover_input(args.input_dir)
            print(f"Auto-selected input: {input_path}")
        if args.max_items is not None and args.max_items < 1:
            raise InputValidationError("--max-items must be a positive integer")
        try:
            research_goal = ResearchGoal.create(
                args.target_compound,
                args.target_class,
                args.target_pathway,
                args.preference_strength,
            )
        except ValueError as exc:
            raise InputValidationError(str(exc)) from exc
        if args.ask_research_goal and not args.resume:
            research_goal = _prompt_research_goal(research_goal)
        elif args.ask_research_goal and args.resume:
            print("Resume mode: using the research goals saved with the original run.")
        if args.ask_deepseek_key:
            key = getpass.getpass("DeepSeek API key (hidden; not saved): ").strip()
            if not key:
                raise InputValidationError("DeepSeek API key cannot be empty")
            os.environ["DEEPSEEK_API_KEY"] = key

        options = WorkflowOptions(
            input_path=input_path,
            runs_dir=args.runs_dir,
            output_dir=args.output_dir,
            resume=args.resume,
            headless=args.headless,
            preflight=not args.no_preflight,
            review=not args.no_review,
            keep_browser_open=not args.close_browser,
            max_items=args.max_items,
            browser_channel=args.browser_channel,
            browser_network=args.browser_network,
            browser_proxy_server=args.browser_proxy_server,
            browser_timeout_ms=args.browser_timeout * 1000,
            research_goal=research_goal,
            kegg_api_enabled=args.enable_kegg_api,
        )
        run_workflow(options)
        return 0
    except InputValidationError as exc:
        print(f"Input error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nInterrupted. Progress was checkpointed and can be resumed.")
        return 130
    except Exception as exc:
        print(f"Workflow failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
