"""Playwright adapter for MetaboAnalyst Pathway Analysis Name check.

Only this module knows about website structure.  The workflow stores plain
candidate dictionaries and never persists browser element handles.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable

from config import BROWSER_TIMEOUT_MS, METABOANALYST_PATHWAY_UPLOAD_URL
from .networking import chromium_network_options


class WebsiteError(RuntimeError):
    pass


class SiteStructureError(WebsiteError):
    pass


class HumanInterventionRequired(WebsiteError):
    pass


def _clean(value: str | None) -> str:
    text = re.sub(r"\s+", " ", value or "").strip()
    return text or "NA"


def _header_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def _xpath_literal(value: str) -> str:
    if "'" not in value:
        return f"'{value}'"
    if '"' not in value:
        return f'"{value}"'
    parts = value.split("'")
    return "concat(" + ", \"'\", ".join(f"'{part}'" for part in parts) + ")"


def _website_query_equivalent(original: str, displayed: str) -> bool:
    """Accept only the trailing punctuation stripping observed on NameMapView."""

    stripped = re.sub(r"[\s,#\]\[+\-]+$", "", original).strip()
    return bool(stripped) and displayed == stripped


def candidate_from_cells(headers: list[str], cells: list[str], selection_key: str, index: int) -> dict[str, Any]:
    values = {_header_key(header): _clean(cells[pos] if pos < len(cells) else "") for pos, header in enumerate(headers)}

    def pick(*names: str) -> str:
        for name in names:
            value = values.get(name, "NA")
            if value != "NA":
                return value
        return "NA"

    name = pick("hit", "name", "matchedname", "compound", "candidate", "match")
    if name == "NA":
        identifier_keys = {"hmdb", "hmdbid", "kegg", "keggid", "pubchem", "pubchemid", "chebi", "metlin"}
        for pos, cell in enumerate(cells):
            if pos < len(headers) and _header_key(headers[pos]) in identifier_keys:
                continue
            cleaned = _clean(cell)
            if cleaned != "NA" and cleaned.casefold() not in {"view", "select"}:
                name = cleaned
                break
    return {
        "name": name,
        "hmdb": pick("hmdb", "hmdbid"),
        "kegg": pick("kegg", "keggid"),
        "pubchem": pick("pubchem", "pubchemid", "cid"),
        "chebi": pick("chebi", "chebiid"),
        "metlin": pick("metlin", "metlinid"),
        "selection_key": selection_key,
        "selection_index": index,
        "source": "MetaboAnalyst View",
    }


class PathwayAnalysisBrowser:
    def __init__(
        self,
        *,
        headless: bool = False,
        browser_channel: str = "chrome",
        network_mode: str = "direct",
        proxy_server: str | None = None,
        timeout_ms: int = BROWSER_TIMEOUT_MS,
    ):
        self.headless = headless
        self.browser_channel = browser_channel
        self.network_mode = network_mode
        self.proxy_server = proxy_server
        self.timeout_ms = timeout_ms
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        self.request_failures: list[dict[str, str]] = []
        self.http_errors: list[dict[str, str]] = []
        self.mapping_query_pages: dict[str, int] = {}
        self.mapping_query_positions: dict[str, tuple[int, int]] = {}
        self.mapping_display_queries: dict[str, str] = {}
        self.expected_queries: list[str] = []
        self.mapping_page_size = 25

    def start(self) -> "PathwayAnalysisBrowser":
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError(
                "Playwright is not installed. Run: pip install -r requirements.txt"
            ) from exc

        self.playwright = sync_playwright().start()
        launch: dict[str, Any] = {
            "headless": self.headless,
            **chromium_network_options(self.network_mode, self.proxy_server),
        }
        if self.browser_channel:
            launch["channel"] = self.browser_channel
        try:
            self.browser = self.playwright.chromium.launch(**launch)
        except Exception:
            if launch.pop("channel", None) is None:
                raise
            self.browser = self.playwright.chromium.launch(**launch)
        self.context = self.browser.new_context(accept_downloads=True)
        self.page = self.context.new_page()
        self.page.set_default_timeout(self.timeout_ms)
        self.page.on(
            "requestfailed",
            lambda request: self.request_failures.append(
                {"url": request.url, "method": request.method, "failure": str(request.failure or "unknown")}
            ),
        )
        self.page.on(
            "response",
            lambda response: self.http_errors.append(
                {"url": response.url, "status": str(response.status)}
            )
            if response.status >= 400
            else None,
        )
        return self

    def close(self) -> None:
        for item in (self.context, self.browser, self.playwright):
            if item is not None:
                try:
                    item.close() if hasattr(item, "close") else item.stop()
                except Exception:
                    pass
        self.page = self.context = self.browser = self.playwright = None

    def __enter__(self) -> "PathwayAnalysisBrowser":
        return self.start()

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def _require_page(self):
        if self.page is None:
            raise RuntimeError("browser has not been started")
        return self.page

    def _dismiss_cookie_banner(self) -> None:
        page = self._require_page()
        for label in ("Essential Only", "OK"):
            button = page.get_by_role("button", name=label, exact=True)
            if button.count() == 1 and button.is_visible():
                button.click()
                return

    def _check_blockers(self) -> None:
        page = self._require_page()
        body_text = page.locator("body").inner_text(timeout=10_000).casefold()
        if any(marker in body_text for marker in ("captcha", "verify you are human", "cloudflare challenge")):
            raise HumanInterventionRequired(
                "MetaboAnalyst requires a CAPTCHA/human check. Complete it in the visible browser, then resume."
            )
        if "your session is about to expire" in body_text:
            keep = page.get_by_text("Yes, keep working", exact=True)
            if keep.count() == 1 and keep.is_visible():
                keep.click()

    def _concentration_file_input(self):
        page = self._require_page()
        forms = page.locator("form")
        matches = []
        for index in range(forms.count()):
            form = forms.nth(index)
            file_inputs = form.locator("input[type=file]")
            if file_inputs.count() != 1:
                continue
            option_labels = form.locator("select option").all_text_contents()
            if any(value.strip().casefold() == "samples in columns" for value in option_labels):
                matches.append(file_inputs.nth(0))
        if len(matches) != 1:
            raise SiteStructureError(
                f"expected one concentration-table file input, found {len(matches)}"
            )
        return matches[0]

    def _upload_scope(self, file_input):
        scope = file_input.locator("xpath=ancestor::form[1]")
        if scope.count() != 1:
            raise SiteStructureError("concentration upload control is not inside one form")
        return scope

    @staticmethod
    def _select_option(scope, label: str) -> None:
        selects = scope.locator("select")
        matches = []
        for index in range(selects.count()):
            select = selects.nth(index)
            options = select.locator("option").all_text_contents()
            if any(option.strip().casefold() == label.casefold() for option in options):
                matches.append(select)
        if len(matches) != 1:
            raise SiteStructureError(f"could not uniquely locate select option {label!r}")
        matches[0].select_option(label=label, force=True)

    @staticmethod
    def _check_label(scope, label: str) -> None:
        control = scope.get_by_label(label, exact=True)
        if control.count() == 1:
            try:
                control.check(force=True)
            except Exception:
                visible_label = scope.locator("label[for]", has_text=label)
                if visible_label.count() != 1:
                    raise
                visible_label.click()
            return
        visible_label = scope.locator("label[for]", has_text=label)
        if visible_label.count() != 1:
            raise SiteStructureError(f"could not uniquely locate choice {label!r}")
        visible_label.click()

    def upload_concentration_table(self, path: Path) -> None:
        page = self._require_page()
        page.goto(METABOANALYST_PATHWAY_UPLOAD_URL, wait_until="domcontentloaded", timeout=self.timeout_ms)
        self._dismiss_cookie_banner()
        self._check_blockers()

        concentration_tab = page.get_by_role("link", name="Concentration Table", exact=True)
        if concentration_tab.count() != 1:
            raise SiteStructureError(
                f"expected one Concentration Table tab, found {concentration_tab.count()}"
            )
        concentration_tab.click()

        file_input = self._concentration_file_input()
        scope = self._upload_scope(file_input)
        self._check_label(scope, "Discrete")
        self._select_option(scope, "Compound Name")
        self._select_option(scope, "Samples in columns")
        file_input.set_input_files(str(path))

        submit_id = file_input.evaluate(
            """el => {
                const form = el.form || el.closest('form');
                if (!form) return '';
                const controls = [...form.querySelectorAll('button, input[type="submit"]')];
                const following = controls.filter(control => {
                    const text = (control.innerText || control.value || '').trim().toLowerCase();
                    const position = el.compareDocumentPosition(control);
                    return text === 'submit' && (position & Node.DOCUMENT_POSITION_FOLLOWING);
                });
                return following.length ? following[0].id : '';
            }"""
        )
        if not submit_id:
            raise SiteStructureError("could not locate the Submit control following the concentration file input")
        submit = page.locator(f"xpath=//*[@id={_xpath_literal(submit_id)}]")
        if submit.count() != 1 or not submit.is_visible() or not submit.is_enabled():
            raise SiteStructureError("concentration Submit control is not uniquely actionable")
        submit.click()
        try:
            page.wait_for_url(
                re.compile(r".*/(?:SanityCheck|NameMapView)\.xhtml(?:;.*|\?.*)?$"),
                timeout=self.timeout_ms,
            )
        except Exception:
            # wait_for_name_check() below provides the richer diagnostic with
            # URL, body message and failed requests.
            pass
        if re.search(r"/SanityCheck\.xhtml(?:;.*|\?.*)?$", page.url):
            # PrimeFaces' generated button is visibly labelled Proceed, but on
            # some runs its accessible name is missing and get_by_role()
            # returns zero controls.  Match the rendered button-text span.
            proceed = page.locator(
                "xpath=//button[.//span[contains(@class, 'ui-button-text') "
                "and normalize-space(.)='Proceed']]"
            )
            try:
                proceed.wait_for(state="visible", timeout=self.timeout_ms)
            except Exception:
                pass
            body = page.locator("body").inner_text(timeout=15_000)
            summary = _clean(body)
            if "Checking data content ...passed." not in summary or proceed.count() != 1:
                raise WebsiteError(
                    "MetaboAnalyst concentration-table integrity check did not pass: "
                    f"Proceed controls={proceed.count()}; {summary[:800]}"
                )
            if not proceed.is_visible() or not proceed.is_enabled():
                raise WebsiteError("Sanity Check passed but its Proceed button is not actionable")
            proceed.click()
        self.wait_for_name_check()

    def upload_compound_list(self, names: list[str]) -> None:
        if not names:
            raise ValueError("compound list is empty")
        self.expected_queries = list(names)
        page = self._require_page()
        page.goto(METABOANALYST_PATHWAY_UPLOAD_URL, wait_until="domcontentloaded", timeout=self.timeout_ms)
        self._dismiss_cookie_banner()
        self._check_blockers()

        compound_tab = page.get_by_role("link", name="Compound List", exact=True)
        if compound_tab.count() != 1:
            raise SiteStructureError(f"expected one Compound List tab, found {compound_tab.count()}")
        compound_tab.click()

        forms = page.locator("form")
        matching_forms = []
        for index in range(forms.count()):
            form = forms.nth(index)
            if form.locator("textarea").count() != 1:
                continue
            options = form.locator("select option").all_text_contents()
            if any(value.strip().casefold() == "compound name" for value in options):
                matching_forms.append(form)
        if len(matching_forms) != 1:
            raise SiteStructureError(f"expected one compound-list form, found {len(matching_forms)}")
        form = matching_forms[0]
        self._select_option(form, "Compound Name")
        form.locator("textarea").fill("\n".join(names))

        submit = form.get_by_role("button", name="Submit", exact=True)
        if submit.count() != 1 or not submit.is_visible() or not submit.is_enabled():
            raise SiteStructureError("compound-list Submit control is not uniquely actionable")
        submit.click()
        self.wait_for_name_check()

    def wait_for_name_check(self) -> None:
        page = self._require_page()
        try:
            page.wait_for_url(re.compile(r".*/NameMapView\.xhtml(?:;.*|\?.*)?$"), timeout=self.timeout_ms)
            page.locator("body").wait_for(state="visible", timeout=15_000)
            body = page.locator("body").inner_text(timeout=15_000)
            if "Name/ID Standardization" not in body:
                raise SiteStructureError("NameMapView loaded without its standardization heading")
        except Exception as exc:
            try:
                self._check_blockers()
            except HumanInterventionRequired:
                raise
            try:
                body = _clean(page.locator("body").inner_text(timeout=5_000))[:500]
            except Exception:
                body = "NA"
            raise WebsiteError(
                f"Name check did not load within {self.timeout_ms // 1000} seconds; "
                f"current URL: {page.url}; page message: {body}; "
                f"last failed requests: {self.request_failures[-3:]}; "
                f"last HTTP errors: {self.http_errors[-3:]}"
            ) from exc

    def _mapping_table(self):
        page = self._require_page()
        tables = page.locator("table")
        matches = []
        for index in range(tables.count()):
            table = tables.nth(index)
            headers = [
                _clean(value)
                for value in table.locator(":scope > thead > tr > th").all_text_contents()
            ]
            keys = {_header_key(value) for value in headers}
            if "query" in keys and ("hit" in keys or "match" in keys):
                matches.append(table)
        if len(matches) != 1:
            raise SiteStructureError(f"expected one Name check mapping table, found {len(matches)}")
        return matches[0]

    def _top_paginator(self):
        page = self._require_page()
        paginator = page.locator(".ui-paginator.ui-paginator-top")
        count = paginator.count()
        if count == 0:
            return None
        if count != 1:
            raise SiteStructureError(f"expected at most one top mapping paginator, found {count}")
        return paginator

    def _active_mapping_page(self) -> int:
        paginator = self._top_paginator()
        if paginator is None:
            return 1
        active = paginator.locator(".ui-paginator-page.ui-state-active")
        if active.count() != 1:
            raise SiteStructureError("mapping paginator has no unique active page")
        try:
            return int(_clean(active.inner_text()))
        except ValueError as exc:
            raise SiteStructureError("mapping paginator active page is not numeric") from exc

    def _mapping_signature(self) -> str:
        table = self._mapping_table()
        rows = table.locator(":scope > tbody > tr")
        count = rows.count()
        first = _clean(rows.nth(0).locator("td").nth(0).inner_text()) if count else "NA"
        last = _clean(rows.nth(count - 1).locator("td").nth(0).inner_text()) if count else "NA"
        return f"{self._active_mapping_page()}|{count}|{first}|{last}"

    def _wait_for_mapping_change(self, previous: str) -> None:
        page = self._require_page()
        page.wait_for_function(
            """previous => {
                const body = document.querySelector("tbody[id$='mapTbl_data']");
                const active = document.querySelector(
                    '.ui-paginator-top .ui-paginator-page.ui-state-active'
                );
                const rows = body ? [...body.querySelectorAll(':scope > tr')] : [];
                const clean = value => (value || '').replace(/\\s+/g, ' ').trim() || 'NA';
                const first = rows.length ? clean(rows[0].querySelector('td')?.innerText) : 'NA';
                const last = rows.length ? clean(rows[rows.length - 1].querySelector('td')?.innerText) : 'NA';
                const signature = `${clean(active?.innerText || '1')}|${rows.length}|${first}|${last}`;
                return signature !== previous;
            }""",
            arg=previous,
            timeout=30_000,
        )

    def _set_max_rows_per_page(self) -> None:
        paginator = self._top_paginator()
        if paginator is None:
            self.mapping_page_size = self._mapping_table().locator(":scope > tbody > tr").count()
            return
        selector = paginator.locator("select.ui-paginator-rpp-options")
        if selector.count() != 1:
            raise SiteStructureError("mapping paginator has no unique rows-per-page selector")
        values = selector.locator("option").evaluate_all(
            "options => options.map(option => option.value)"
        )
        numeric = [int(value) for value in values if str(value).isdigit()]
        if not numeric:
            raise SiteStructureError("mapping paginator exposes no numeric page sizes")
        target = max(numeric)
        current = int(selector.evaluate("element => element.value"))
        self.mapping_page_size = current
        next_control = paginator.locator("a.ui-paginator-next")
        next_class = next_control.get_attribute("class") or "" if next_control.count() == 1 else ""
        if current == target or "ui-state-disabled" in next_class:
            return
        previous = self._mapping_signature()
        selector.select_option(value=str(target))
        self._wait_for_mapping_change(previous)
        self.mapping_page_size = target

    def _click_paginator_control(self, selector: str) -> None:
        paginator = self._top_paginator()
        if paginator is None:
            raise SiteStructureError("mapping table has no paginator")
        control = paginator.locator(selector)
        if control.count() != 1:
            raise SiteStructureError(f"mapping paginator control is not unique: {selector}")
        classes = control.get_attribute("class") or ""
        if "ui-state-disabled" in classes:
            raise SiteStructureError(f"mapping paginator control is disabled: {selector}")
        previous = self._mapping_signature()
        control.click()
        self._wait_for_mapping_change(previous)

    def _goto_mapping_page(self, target: int) -> None:
        if target < 1:
            raise ValueError("mapping page numbers start at 1")
        paginator = self._top_paginator()
        if paginator is None:
            if target != 1:
                raise SiteStructureError(f"mapping table has no page {target}")
            return
        active = self._active_mapping_page()
        if active > target:
            self._click_paginator_control("a.ui-paginator-first")
            active = self._active_mapping_page()
        while active < target:
            before = active
            self._click_paginator_control("a.ui-paginator-next")
            active = self._active_mapping_page()
            if active <= before:
                raise SiteStructureError("mapping paginator did not advance")
        if active != target:
            raise SiteStructureError(f"could not navigate to mapping page {target}; active page is {active}")

    def _read_visible_mapping_rows(self) -> list[dict[str, str]]:
        table = self._mapping_table()
        headers = [
            _clean(value) for value in table.locator(":scope > thead > tr > th").all_text_contents()
        ]
        rows = []
        body_rows = table.locator(":scope > tbody > tr")
        for index in range(body_rows.count()):
            tr = body_rows.nth(index)
            cells = [_clean(value) for value in tr.locator("td").all_text_contents()]
            if not cells:
                continue
            raw = {_header_key(header): cells[pos] if pos < len(cells) else "NA" for pos, header in enumerate(headers)}
            query_cell = tr.locator("td").nth(0)
            marker = " ".join(
                filter(None, [query_cell.get_attribute("class"), query_cell.get_attribute("style")])
            ).casefold()
            hit = raw.get("hit", raw.get("match", "NA"))
            warning = any(word in marker for word in ("red", "orange", "warn", "danger", "error"))
            matched = hit not in {"", "NA", "No Match", "No match"} and not warning
            rows.append(
                {
                    "Query": raw.get("query", cells[0]),
                    "Match": hit,
                    "HMDB": raw.get("hmdb", raw.get("hmdbid", "NA")),
                    "KEGG": raw.get("kegg", raw.get("keggid", "NA")),
                    "PubChem": raw.get("pubchem", raw.get("pubchemid", "NA")),
                    "ChEBI": raw.get("chebi", raw.get("chebiid", "NA")),
                    "MetLin": raw.get("metlin", raw.get("metlinid", "NA")),
                    "SMILES": raw.get("smiles", "NA"),
                    "Comment": "1" if matched else "0",
                }
            )
        return rows

    def read_mapping_rows(self) -> list[dict[str, str]]:
        """Read every PrimeFaces page and cache the page for each Query."""

        self._set_max_rows_per_page()
        self._goto_mapping_page(1)
        self.mapping_query_pages = {}
        self.mapping_query_positions = {}
        self.mapping_display_queries = {}
        collected: list[tuple[dict[str, str], int, int]] = []
        while True:
            page_number = self._active_mapping_page()
            visible = self._read_visible_mapping_rows()
            print(f"Reading Name check page {page_number}: {len(visible)} rows")
            for row_index, row in enumerate(visible):
                collected.append((row, page_number, row_index))

            paginator = self._top_paginator()
            if paginator is None:
                break
            next_control = paginator.locator("a.ui-paginator-next")
            if next_control.count() != 1:
                raise SiteStructureError("mapping paginator has no unique Next control")
            classes = next_control.get_attribute("class") or ""
            if "ui-state-disabled" in classes:
                break
            self._click_paginator_control("a.ui-paginator-next")

        if self.expected_queries and len(collected) == len(self.expected_queries):
            aligned: list[dict[str, str]] = []
            for original, (row, page_number, row_index) in zip(
                self.expected_queries, collected, strict=True
            ):
                displayed = str(row.get("Query", "")).strip()
                if displayed != original and not _website_query_equivalent(original, displayed):
                    raise SiteStructureError(
                        "website changed a Query in an unrecognized way at input position "
                        f"{len(aligned) + 1}: {original!r} became {displayed!r}"
                    )
                row["Query"] = original
                self.mapping_query_pages[original] = page_number
                self.mapping_query_positions[original] = (page_number, row_index)
                self.mapping_display_queries[original] = displayed
                aligned.append(row)
            return aligned

        rows: list[dict[str, str]] = []
        for row, page_number, row_index in collected:
            query = row.get("Query", "")
            if query in self.mapping_query_pages:
                raise SiteStructureError(f"website mapping contains duplicate Query {query!r}")
            self.mapping_query_pages[query] = page_number
            self.mapping_query_positions[query] = (page_number, row_index)
            self.mapping_display_queries[query] = query
            rows.append(row)
        return rows

    def download_mapping(self, destination: Path) -> bool:
        """Download when a clearly identified mapping export control is present."""

        page = self._require_page()
        candidates = page.locator(
            "a[id*='download' i], button[id*='download' i], "
            "input[id*='download' i], a[href*='download' i]"
        )
        clear = []
        for index in range(candidates.count()):
            item = candidates.nth(index)
            identity = " ".join(
                filter(
                    None,
                    [
                        item.get_attribute("id"),
                        item.get_attribute("href"),
                        item.get_attribute("value"),
                        item.inner_text(),
                    ],
                )
            ).casefold()
            if "map" in identity and item.is_visible():
                clear.append(item)
        if len(clear) != 1:
            return False
        try:
            with page.expect_download(timeout=15_000) as download_info:
                clear[0].click()
            destination.parent.mkdir(parents=True, exist_ok=True)
            download_info.value.save_as(str(destination))
            return True
        except Exception:
            return False

    def _row_for_query(self, query: str):
        page_number = self.mapping_query_pages.get(query)
        if page_number is None:
            # A downloaded mapping snapshot does not populate the DOM page
            # cache.  Build it lazily before locating the row.
            self.read_mapping_rows()
            page_number = self.mapping_query_pages.get(query)
        if page_number is None:
            raise SiteStructureError(f"website mapping has no row for {query!r}")
        self._goto_mapping_page(page_number)
        table = self._mapping_table()
        position = self.mapping_query_positions.get(query)
        displayed = self.mapping_display_queries.get(query, query)
        if position is not None and position[0] == page_number:
            body_rows = table.locator(":scope > tbody > tr")
            if position[1] >= body_rows.count():
                raise SiteStructureError(f"cached row position for {query!r} is outside the current page")
            row = body_rows.nth(position[1])
            actual = _clean(row.locator("td").nth(0).inner_text())
            if actual != displayed:
                raise SiteStructureError(
                    f"cached website row for {query!r} now contains {actual!r} instead of {displayed!r}"
                )
        else:
            row = table.locator(
                f"xpath=./tbody/tr[td[1][normalize-space(.)={_xpath_literal(displayed)}]]"
            )
        if row.count() != 1:
            raise SiteStructureError(f"expected one row for {query!r}, found {row.count()}")
        return row

    def _open_view(self, query: str):
        row = self._row_for_query(query)
        view = row.get_by_text("View", exact=True)
        if view.count() != 1:
            raise SiteStructureError(f"expected one View control in row {query!r}, found {view.count()}")
        view.click()
        page = self._require_page()
        # PrimeFaces displays a temporary modal saying "Processing ..." while
        # the View contents are fetched.  It is a real ``.ui-dialog`` too, so
        # selecting the first visible dialog races with the candidate popup.
        # Locate the semantic candidate dialog and explicitly exclude the
        # transient waiting layer.
        displayed = self.mapping_display_queries.get(query, query)
        dialogs = page.locator("[role=dialog]:visible, .ui-dialog:visible").filter(
            has_not_text=re.compile(r"Processing|please be patient", re.IGNORECASE)
        ).filter(has_text=f"Query name: {displayed}")
        dialogs.last.wait_for(state="visible", timeout=30_000)
        count = dialogs.count()
        if count == 0:
            raise SiteStructureError(f"candidate dialog for {query!r} was not rendered")

        # NameMapView currently emits duplicate dialog nodes when several
        # unresolved rows are uploaded.  They contain identical AJAX-updated
        # content and duplicate ids.  The active PrimeFaces instance is the
        # top-most/last one, so rank by computed z-index and then DOM order.
        layers = dialogs.evaluate_all(
            "els => els.map((el, index) => ({"
            "index, z: Number.parseInt(getComputedStyle(el).zIndex || '0', 10) || 0"
            "}))"
        )
        active_index = max(layers, key=lambda item: (item["z"], item["index"]))["index"]
        return dialogs.nth(active_index)

    @staticmethod
    def _parse_dialog(dialog) -> list[dict[str, Any]]:
        tables = dialog.locator("table")
        for table_index in range(tables.count()):
            table = tables.nth(table_index)
            headers = [
                _clean(value)
                for value in table.locator(":scope > thead > tr > th").all_text_contents()
            ]
            # The current site uses PrimeFaces checkboxes.  Older deployments
            # used radios, so support both.  Require an actual name column to
            # avoid mistaking the outer layout table for the nested result
            # table (the outer table also contains the same controls).
            header_keys = {_header_key(value) for value in headers}
            if not header_keys.intersection(
                {"hit", "name", "matchedname", "compound", "candidate", "match"}
            ):
                continue
            candidates: list[dict[str, Any]] = []
            rows = table.locator(":scope > tbody > tr")
            for row_index in range(rows.count()):
                row = rows.nth(row_index)
                control = row.locator("input[type=radio], input[type=checkbox]")
                if control.count() != 1:
                    continue
                cells = [_clean(value) for value in row.locator("td").all_text_contents()]
                value = control.get_attribute("value") or str(row_index)
                candidate = candidate_from_cells(headers, cells, value, row_index)
                candidate["selection_id"] = control.get_attribute("id") or ""
                if (
                    candidate["name"] != "NA"
                    and "none of the above" not in candidate["name"].casefold()
                ):
                    candidates.append(candidate)
            return candidates
        return []

    @staticmethod
    def _close_dialog(dialog) -> None:
        for label in ("Cancel", "Close"):
            control = dialog.get_by_text(label, exact=True)
            if control.count() == 1 and control.is_visible():
                control.click()
                dialog.wait_for(state="hidden", timeout=15_000)
                return
        icon = dialog.locator("[aria-label=Close], .ui-dialog-titlebar-close")
        if icon.count() == 1:
            icon.click()
            dialog.wait_for(state="hidden", timeout=15_000)
            return
        raise SiteStructureError("candidate dialog has no unique Cancel/Close control")

    def inspect_candidates(self, query: str) -> list[dict[str, Any]]:
        self._check_blockers()
        dialog = self._open_view(query)
        candidates = self._parse_dialog(dialog)
        self._close_dialog(dialog)
        return candidates

    @staticmethod
    def _same_candidate(left: dict[str, Any], right: dict[str, Any]) -> bool:
        if _clean(left.get("name", "")).casefold() == _clean(right.get("name", "")).casefold():
            return True
        for field in ("hmdb", "kegg", "pubchem", "chebi", "metlin"):
            a = _clean(left.get(field, "NA"))
            b = _clean(right.get(field, "NA"))
            if a != "NA" and a == b:
                return True
        return False

    def apply_candidate(self, query: str, expected: dict[str, Any]) -> dict[str, str]:
        self._check_blockers()
        dialog = self._open_view(query)
        current = self._parse_dialog(dialog)
        matching = [item for item in current if self._same_candidate(item, expected)]
        if len(matching) != 1:
            self._close_dialog(dialog)
            raise SiteStructureError(
                f"saved candidate for {query!r} is no longer unique/present on the website"
            )
        selected = matching[0]
        control_id = str(selected.get("selection_id", ""))
        key = str(selected.get("selection_key", ""))
        control = (
            dialog.locator(f"xpath=.//input[@id={_xpath_literal(control_id)}]")
            if control_id
            else dialog.locator("xpath=./__no_saved_control__")
        )
        if control.count() != 1:
            control = dialog.locator(
                "xpath=.//input[(@type='radio' or @type='checkbox') "
                f"and @value={_xpath_literal(key)}]"
            )
        if control.count() != 1:
            index = int(selected.get("selection_index", -1))
            controls = dialog.locator("input[type=radio], input[type=checkbox]")
            if index < 0 or index >= controls.count():
                self._close_dialog(dialog)
                raise SiteStructureError("candidate selection control cannot be re-identified")
            control = controls.nth(index)
        try:
            control.check(force=True)
        except Exception:
            widget = control.locator(
                "xpath=ancestor::*[contains(concat(' ', normalize-space(@class), ' '), ' ui-chkbox ')][1]"
            )
            if widget.count() != 1:
                raise
            widget.locator(".ui-chkbox-box").click()

        ok_controls = dialog.get_by_text("OK", exact=True)
        if ok_controls.count() != 1:
            ok_controls = dialog.get_by_text("Confirm", exact=True)
        if ok_controls.count() != 1:
            raise SiteStructureError("candidate dialog has no unique OK/Confirm control")
        ok_controls.click()
        dialog.wait_for(state="hidden", timeout=30_000)

        row = self._row_for_query(query)
        values = [_clean(value) for value in row.locator("td").all_text_contents()]
        if not any(self._same_candidate(selected, {"name": value}) for value in values):
            identifiers = [
                _clean(selected.get(field, "NA"))
                for field in ("hmdb", "kegg", "pubchem", "chebi", "metlin")
            ]
            if not any(value != "NA" and value in values for value in identifiers):
                raise WebsiteError(f"website did not visibly confirm the selection for {query!r}")
        return {
            "Query": query,
            "Match": selected.get("name", "NA"),
            "HMDB": selected.get("hmdb", "NA"),
            "KEGG": selected.get("kegg", "NA"),
            "PubChem": selected.get("pubchem", "NA"),
            "ChEBI": selected.get("chebi", "NA"),
            "MetLin": selected.get("metlin", "NA"),
            "SMILES": "NA",
            "Comment": "1",
        }

    def keep_open_for_operator(self) -> None:
        input("Browser remains on Name check. Press Enter here when you are ready to close it... ")


def mapping_by_query(rows: Iterable[dict[str, str]]) -> dict[str, dict[str, str]]:
    return {row.get("Query", ""): row for row in rows if row.get("Query")}
