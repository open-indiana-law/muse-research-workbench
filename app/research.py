"""Typed research loop. Fixture planner tonight; Spark when credits land."""

from __future__ import annotations

import hashlib
import json
import re
import httpx
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.law_gateway import DEFAULT_MCP_URL, LawGateway, LiveMcp
from app.research_state import authority_notice_conflict, admitted_evidence_gaps, build_research_state, source_limit, state_message
from app.source_reader import opened_sources
from app.muse_client import (
    DEVELOPER,
    MAX_SPARK_TURNS,
    CreditNotReady,
    assistant_text,
    parse_tool_calls,
    spark_ready,
    spark_turn,
)

DISCLAIMER = (
    "Unofficial copy — verify at the official source — not legal advice — not a citator."
)
CITE_RE = re.compile(
    r"\b(?:IC|I\.C\.|Ind\.\s*Code)\s*§?\s*(\d+(?:\.\d+)?-\d+-\d+-\d+)\b",
    re.IGNORECASE,
)
# Single-quote ambiguity is conservative: check the whole outer passage,
# including possessives/newlines, rather than certifying only a prefix.
QUOTE_RE = re.compile(r'["“]([^"”]+)["”]|(?<!\w)\'(.+)\'(?!\w)|(?<!\w)‘(.+)’(?!\w)', re.DOTALL)
CASELAW_CATCH = (
    "Text matches only. Not a citator. Not treatment. Not good law. "
    "The URL is the tool's CourtListener link, not an independently verified official slip."
)
MAX_SOURCE_CHARS = 100_000
MAX_CONTEXT_CHARS = 350_000
MAX_TOOL_CALLS = 20
# Narrow reviewed demo links, checked against official PDFs November 2, 2026.
# Engine URLs remain visible separately; this is not a general resolver/citator.
OFFICIAL_DEMO_OPINIONS = {
    'incourts-1106156996': 'https://public.courts.in.gov/Decisions/api/Document/Opinion?Id=gF3dWWM2bvtfqybmSNtVTM7Ii16McF3rZO7iqeN5xdaFFy950LCm5-XaXJp8uutd0',
    '2100393': 'https://public.courts.in.gov/Decisions/api/Document/Opinion?Id=TWsbfXFBad9y9vdvFD9GFhC4mHXcP-9XK09fyApK3esxyexcQKoUxUH3WnmR-fcQ0',
    '852407': 'https://public.courts.in.gov/Decisions/api/Document/Opinion?Id=1TFGzZtVKPUyQm3ZSmG0U_FBjkoycBQxjN3Rkjy0OeESn5v8NODE2Fat3ms35hBf0',
}


@dataclass
class TurnResult:
    question: str
    mode: str
    planner: str
    found: bool
    catch: str | None
    summary: str
    disclaimer: str
    steps: list[dict[str, Any]] = field(default_factory=list)
    spark_ready: bool = False
    tool_names: list[str] = field(default_factory=list)
    quotes_ok: bool = True
    quote_failures: list[str] = field(default_factory=list)
    source_cards: list[dict[str, Any]] = field(default_factory=list)
    complete: bool = True
    completion_state: str = "complete"
    completion_issues: list[str] = field(default_factory=list)
    research_state: dict[str, Any] = field(default_factory=dict)
    opened_sources: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def extract_citation(question: str) -> str | None:
    match = CITE_RE.search(question)
    if not match:
        return None
    return f"IC {match.group(1)}"


def classify(question: str) -> str:
    text = question.lower()
    cite = extract_citation(question) or ""
    if "99-1-1-1" in cite or "99-99-99-99" in text or "fake cite" in text:
        return "bad_cite"
    if any(word in text for word in ("amend", "change", "version", "currency", "snapshot", "since 20", "before 20")):
        return "currency"
    if cite or "income withholding" in text or "income payor" in text or "31-16-15-25" in text:
        return "statute"
    if any(token in text for token in ("horton", "what it cites", "open horton")):
        return "caselaw"
    return "search"


def _excerpt(text: str, limit: int = 900) -> str:
    compact = " ".join((text or "").split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1] + "…"


def _versions_catch(versions: dict[str, Any]) -> str | None:
    groups = versions.get("versions") or []
    if len(groups) > 1:
        years = []
        for group in groups:
            snap = group.get("snapshot_years") or []
            if snap:
                years.append(f"{snap[0]}–{snap[-1]}" if len(snap) > 1 else str(snap[0]))
        joined = ", ".join(years) if years else f"{len(groups)} groups"
        return (
            f"Currency catch: this section has more than one unofficial snapshot group ({joined}). "
            "Do not treat the displayed text as the only dated copy."
        )
    return None


def _missing_catch(resolved: dict[str, Any]) -> str | None:
    for item in resolved.get("citations") or []:
        if item.get("exists_in_latest_snapshot") is False:
            citation = item.get("citation") or item.get("section_id")
            return (
                f"Bad-cite catch: {citation} is not in the latest unofficial snapshot. "
                "The tool miss is the answer; no section text was invented."
            )
    if not (resolved.get("citations") or []):
        return "Bad-cite catch: no citation parsed. No section text was invented."
    return None


def _summarize_statute(section: dict[str, Any], catch: str | None) -> str:
    heading = section.get("heading") or "Section"
    section_id = section.get("section_id") or ""
    year = section.get("snapshot_year") or section.get("as_of") or "unknown snapshot"
    body = _excerpt(section.get("text") or section.get("body") or "")
    parts = [
        f"{heading} (IC {section_id}, unofficial snapshot {year}).",
        body,
        DISCLAIMER,
    ]
    if catch:
        parts.append(catch)
    return "\n\n".join(part for part in parts if part)


def _flatten_strings(obj: Any) -> list[str]:
    out: list[str] = []
    if isinstance(obj, str):
        if obj.strip():
            out.append(obj)
    elif isinstance(obj, dict):
        for value in obj.values():
            out.extend(_flatten_strings(value))
    elif isinstance(obj, list):
        for value in obj:
            out.extend(_flatten_strings(value))
    elif obj is not None and not isinstance(obj, bool):
        out.append(str(obj))
    return out


def quote_failures(summary: str, results: list[Any], extra: list[str] | None = None) -> list[str]:
    """Wording check against source bodies and closed classifier labels.

    This does not bind a quote to a named case or certify its legal meaning.
    """
    blobs = list(extra or [])
    for result in results:
        if isinstance(result, dict) and result.get('found') is not False:
            for key in ('text', 'body'):
                if isinstance(result.get(key), str):
                    blobs.append(result[key])
            # Describing an observed enum is different from validating an
            # arbitrary metadata/query sentence as an opinion quotation.
            if result.get('disposition') in {'affirmed', 'reversed', 'remanded', 'mixed', 'unlabeled', 'unknown'}:
                blobs.append(result['disposition'])
            cluster = str(result.get('cluster_id') or '')
            if re.fullmatch(r'(?:incourts-)?[0-9]{1,20}', cluster):
                blobs.append(cluster)
    # Typographic apostrophes carry no wording difference; retain every word
    # and all other punctuation so substantive quote changes still fail.
    apostrophes = str.maketrans({"’": "'", "‘": "'"})
    corpus = [" ".join(blob.split()).lower().translate(apostrophes) for blob in blobs]
    failures: list[str] = []
    quotations = [next(group for group in match.groups() if group is not None)
                  for match in QUOTE_RE.finditer(summary or '')]
    # Markdown blockquotes also imply verbatim text, even without quote marks.
    for blockquote in re.findall(r'(?m)^[ \t]*>[ \t]?(.*\S)', summary or ''):
        # A matching pair wrapping the entire block is presentation syntax,
        # just as for inline quotations above. Keep every interior character.
        pairs = {'"': '"', '“': '”', "'": "'", '‘': '’'}
        if len(blockquote) >= 2 and pairs.get(blockquote[0]) == blockquote[-1]:
            blockquote = blockquote[1:-1]
        quotations.append(blockquote)
    for quote in quotations:
        needle = " ".join(quote.split()).lower().translate(apostrophes)
        if needle and not any(needle in blob for blob in corpus):
            failures.append(quote)
    return failures


def _pick_named_hit(results: list[dict[str, Any]], token: str) -> dict[str, Any] | None:
    named = [item for item in results if token in (item.get("case_name") or "").lower()]
    pool = named or results
    return pool[0] if pool else None


def _case_card(payload: dict[str, Any], *, role: str) -> dict[str, Any]:
    return {
        "kind": "case",
        "role": role,
        "title": payload.get("case_name"),
        "cluster_id": payload.get("cluster_id"),
        "date_filed": payload.get("date_filed"),
        "court": payload.get("court"),
        "decision_form": payload.get("decision_form"),
        "citability": payload.get("citability"),
        "precedential_status": payload.get("precedential_status"),
        "url": payload.get("url"),
        "note": CASELAW_CATCH,
    }


def _summarize_caselaw(opinion: dict[str, Any], cited: dict[str, Any]) -> str:
    name = opinion.get("case_name") or "Untitled cluster"
    court = opinion.get("court") or "Indiana appellate court"
    filed = opinion.get("date_filed") or "unknown date"
    form = opinion.get("decision_form") or "unlabeled form"
    status = opinion.get("precedential_status") or "status unlabeled"
    citability = opinion.get("citability") or "citability unlabeled"
    cluster = opinion.get("cluster_id") or ""
    url = opinion.get("url") or "no URL returned"
    snippet = _excerpt(opinion.get("text") or "", 420)
    lines = [
        f"{name} ({court}, filed {filed}, {status.lower()} {form}, citability {citability}, cluster {cluster}).",
        f"Tool URL: {url}",
        snippet,
    ]
    hits = cited.get("results") or []
    if hits:
        names = []
        for item in hits[:8]:
            cited_name = item.get("case_name") or item.get("cluster_id")
            cited_date = item.get("date_filed") or "undated"
            names.append(f"{cited_name} ({cited_date})")
        lines.append("Text-match cites in this opinion: " + "; ".join(names) + ".")
    else:
        lines.append("No reporter or Rule 22 text-match cites were indexed for this opinion.")
    lines.append(CASELAW_CATCH)
    lines.append(DISCLAIMER)
    return "\n\n".join(lines)


async def _run_caselaw(gateway: LawGateway, question: str) -> TurnResult:
    query = "Horton" if "horton" in question.lower() else question
    args: dict[str, Any] = {"query": query, "limit": 5}
    if query.lower() == "horton":
        args["form"] = "memorandum"
    search = await gateway.invoke("case_search", args)
    hit = _pick_named_hit(search.get("results") or [], "horton" if query.lower() == "horton" else "")
    if not hit:
        return TurnResult(
            question=question,
            mode="fixture",
            planner="caselaw",
            found=False,
            catch="No unofficial case search hit. No opinion text was invented.",
            summary=DISCLAIMER,
            disclaimer=DISCLAIMER,
        )
    cluster_id = str(hit.get("cluster_id") or "")
    opinion = await gateway.invoke("case_get", {"cluster_id": cluster_id})
    if not opinion.get("found"):
        return TurnResult(
            question=question,
            mode="fixture",
            planner="caselaw",
            found=False,
            catch="Case search hit a cluster the fetch missed. No opinion text was invented.",
            summary=DISCLAIMER,
            disclaimer=DISCLAIMER,
            source_cards=[_case_card(hit, role="search-hit")],
        )
    cited = await gateway.invoke("cases_cited_in", {"query": cluster_id, "limit": 8})
    cards = [_case_card(opinion, role="opened")]
    for item in (cited.get("results") or [])[:8]:
        cards.append(_case_card(item, role="text-match-cite"))
    return TurnResult(
        question=question,
        mode="fixture",
        planner="caselaw",
        found=True,
        catch=CASELAW_CATCH,
        summary=_summarize_caselaw(opinion, cited),
        disclaimer=DISCLAIMER,
        source_cards=cards,
    )


def _finish(result: TurnResult, gateway: LawGateway) -> TurnResult:
    if result.completion_state != "complete":
        result.completion_issues.append(result.completion_state)
    if not result.source_cards:
        for step in gateway.steps:
            source = step.result
            if step.tool not in {"ic_get_companion", "ic_get_section", "case_get"} or not source.get("found"):
                continue
            result.source_cards.append({
                "kind": source.get("kind") or step.tool,
                "role": "opened", "title": source.get("title") or source.get("case_name") or source.get("heading"),
                "url": source.get("url") or source.get("source_url") or source.get("source_page"),
                **{key: source[key] for key in ("doc_id", "page", "year", "compiled_on", "section_id", "cluster_id", "court", "date_filed", "snapshot_year", "decision_form", "citability") if key in source},
                "note": DISCLAIMER,
            })
    for card in result.source_cards:
        official = OFFICIAL_DEMO_OPINIONS.get(str(card.get('cluster_id')))
        if official:
            card['official_url'] = official
    extras = [DISCLAIMER, CASELAW_CATCH]
    failures = quote_failures(result.summary, [step.result for step in gateway.steps], extra=extras)
    if failures:
        result.complete = False
        result.completion_state = "quote_failed"
        result.completion_issues.append("quote_failed")
        result.quote_failures = failures
        result.quotes_ok = False
        result.catch = (
            (result.catch + " " if result.catch else "")
            + "Quote check: a quoted span was not verified in the retrieved bodies or classifier labels; the answer was withheld."
        )
        result.summary = (
            "Quote check failed. The tools returned sources, but the answer used wording they did not. "
            "The unverified quoted span may be a rejected user suggestion; this check does not determine intent.\n\n"
            + DISCLAIMER
        )
    result.steps = [_step_dict(step) for step in gateway.steps]
    result.spark_ready = spark_ready()
    return result


async def _run_tools(gateway: LawGateway, kind: str, question: str, as_of: str | None) -> TurnResult:
    if kind == "caselaw":
        return _finish(await _run_caselaw(gateway, question), gateway)
    cite = extract_citation(question) or "IC 31-16-15-25"
    if kind == "search" and not extract_citation(question):
        search = await gateway.invoke("ic_search", {"query": question, "limit": 5})
        hits = search.get("results") or []
        if not hits:
            return _finish(
                TurnResult(
                    question=question,
                    mode="fixture",
                    planner="search",
                    found=False,
                    catch="No unofficial search hit. No citation was invented.",
                    summary=DISCLAIMER,
                    disclaimer=DISCLAIMER,
                ),
                gateway,
            )
        first = hits[0]
        cite = first.get("citation") or f"IC {first.get('section_id')}"
    resolved = await gateway.invoke("ic_resolve_citation", {"text": cite})
    miss = _missing_catch(resolved)
    if miss or kind == "bad_cite":
        return _finish(
            TurnResult(
                question=question,
                mode="fixture",
                planner=kind,
                found=False,
                catch=miss or "Bad-cite catch: citation did not resolve to a live section.",
                summary=miss or DISCLAIMER,
                disclaimer=DISCLAIMER,
            ),
            gateway,
        )
    section_id = (resolved.get("citations") or [{}])[0].get("section_id")
    args: dict[str, Any] = {"section_id": section_id}
    if as_of:
        args["as_of"] = as_of
    section = await gateway.invoke("ic_get_section", args)
    versions = await gateway.invoke("ic_get_versions", {"section_id": section_id})
    catch = _versions_catch(versions)
    if kind == "currency" and not catch:
        catch = "Currency check ran; only one unofficial snapshot group was returned."
    found = bool(section.get("found"))
    cards = []
    if found:
        cards.append(
            {
                "kind": "statute",
                "role": "opened",
                "title": section.get("heading"),
                "section_id": section.get("section_id"),
                "snapshot_year": section.get("snapshot_year"),
                "url": section.get("url") or "https://mcp.openindianalaw.org/",
                "note": DISCLAIMER,
            }
        )
    return _finish(
        TurnResult(
            question=question,
            mode="fixture",
            planner=kind,
            found=found,
            catch=catch,
            summary=_summarize_statute(section, catch) if found else DISCLAIMER,
            disclaimer=DISCLAIMER,
            source_cards=cards,
        ),
        gateway,
    )


def _step_dict(step: Any) -> dict[str, Any]:
    result = step.result if isinstance(step.result, dict) else {"value": step.result}
    digest = hashlib.sha256(json.dumps(result, sort_keys=True, default=str).encode()).hexdigest()[:12]
    slim = {key: result.get(key) for key in ("found", "section_id", "heading", "snapshot_year", "citation") if key in result}
    if "citations" in result:
        slim["citations"] = [
            {k: item.get(k) for k in ("section_id", "citation", "exists_in_latest_snapshot")}
            for item in (result.get("citations") or [])[:5]
        ]
    if "versions" in result:
        slim["version_groups"] = len(result.get("versions") or [])
    if "results" in result:
        slim["result_count"] = len(result.get("results") or [])
    if "text" in result:
        slim["text_excerpt"] = _excerpt(str(result.get("text") or ""), 280)
        slim["text_ending"] = str(result.get("text") or "")[-1200:]
    for key in ("cluster_id", "case_name", "date_filed", "citability", "decision_form", "url", "match_count",
                "doc_id", "title", "kind", "year", "page", "page_count", "compiled_on", "source_page", "unofficial",
                "disposition", "disposition_quote", "disposition_method"):
        if key in result:
            slim[key] = result.get(key)
    slim["result_sha256_12"] = digest
    return {"tool": step.tool, "arguments": step.arguments, "result": slim}


async def research_fixture(question: str, *, as_of: str | None = None, url: str = DEFAULT_MCP_URL) -> TurnResult:
    async with LiveMcp(url) as mcp:
        gateway = LawGateway(call_tool=mcp.call)
        kind = classify(question)
        result = await _run_tools(gateway, kind, question, as_of)
        result.tool_names = mcp.tool_names
        return result


def note_word_count(text: str) -> int:
    """Count note body plus source notes; a short standalone title is separate."""
    parts=re.split(r'\n\s*\n',text.strip(),maxsplit=1)
    if len(parts)==2 and len(parts[0].split())<=16 and re.match(r'^(?:#{1,6}\s+|\*\*)?research note\b',parts[0],re.I):
        text=parts[1]
    return len(text.split())


async def _spark_loop(
    question: str,
    *,
    as_of: str | None,
    gateway: LawGateway,
    turn,
    source_call_limit: int,
) -> tuple[str, str | None, str, dict[str, Any]]:
    user = question if not as_of else f"{question}\nRequested as_of={as_of}"
    messages: list[dict[str, Any]] = [
        {"role": "developer", "content": DEVELOPER},
        {"role": "user", "content": user},
    ]
    final = ""
    state = "turn_limit"
    tool_count = 0
    attempted_finals: list[dict[str, Any]] = []
    reconsidered = False
    length_revised = False
    authority_reconsidered = False
    quote_format_revised = False
    word_range = re.search(r"\b(\d+)\s*[-–]\s*(\d+)\s*[- ]?\s*words?\b", question, re.I)
    length_bounds = tuple(map(int, word_range.groups())) if word_range else None
    if length_bounds and not (0 < length_bounds[0] <= length_bounds[1] <= 2000):
        length_bounds = None
    reconsidered_at_sources = 0
    outstanding_gaps: list[str] = []
    for turn_index in range(MAX_SPARK_TURNS):
        observed = build_research_state(question, gateway.steps, source_call_limit,
                                        attempted_finals=attempted_finals,
                                        gap_reconsideration_used=reconsidered)
        request_messages = [messages[0], state_message(observed), *messages[1:]]
        if len(json.dumps(request_messages, default=str)) > MAX_CONTEXT_CHARS:
            state = "context_limit"
            break
        try:
            body = await turn(request_messages)
            calls = parse_tool_calls(body)
            choice = (body.get("choices") or [{}])[0]
        except CreditNotReady:
            if not gateway.steps:
                raise
            state = "credit_limit"
            break
        except (httpx.HTTPError, TimeoutError):
            state = "transport_error"
            break
        except (ValueError, TypeError, AttributeError, IndexError):
            # Malformed provider JSON/shapes and rejected tool calls must not
            # discard sources already retrieved or trigger an implicit retry.
            state = "invalid_response"
            break
        if quote_format_revised and calls:
            # This one-shot correction may only restate already opened evidence.
            # Refuse unexpected retrieval instead of dispatching it.
            state = "model_incomplete"
            break
        messages.append(choice.get("message") or {"role": "assistant", "content": assistant_text(body)})
        if not calls:
            final = assistant_text(body)
            attempted_finals.append({'text':final, 'reported_evidence_gaps':[]})
            state = ("output_limit" if choice.get("finish_reason") == "length"
                     else "model_incomplete" if choice.get("finish_reason") not in (None, "stop")
                     else "complete" if final.strip() else "empty_answer")
            if state == "complete":
                opened = any(s.tool in {'case_get', 'ic_get_section', 'ic_get_companion'}
                             and s.result.get('found') is True
                             and (s.result.get('text') or s.result.get('body'))
                             for s in gateway.steps)
                missing = [s.result for s in gateway.steps if s.tool == 'ic_resolve_citation'
                           and s.result.get('citations')
                           and all(c.get('exists_in_latest_snapshot') is False
                                   for c in s.result['citations'])]
                if not opened:
                    if missing:
                        # A verified miss supports only this deterministic limited answer.
                        final = _missing_catch(missing[-1]) or DISCLAIMER
                    else:
                        state = "no_evidence"
            if state == "complete" and build_research_state(question, gateway.steps, source_call_limit)['missing_evidence']:
                state = "missing_required_sources"
            if state in {'complete', 'missing_required_sources'}:
                gaps = admitted_evidence_gaps(final)
                if reconsidered and not gaps:
                    # Merely removing a caveat or finding another search lead
                    # does not close a previously admitted missing-body gap.
                    def body_identity(step):
                        data = step.result if isinstance(step.result, dict) else {}
                        body = data.get('text') or data.get('body')
                        if (step.tool not in {'ic_get_section', 'case_get', 'ic_get_companion'}
                                or data.get('found') is not True
                                or not isinstance(body, str) or not body.strip()):
                            return None
                        return (step.tool, hashlib.sha256(body.encode()).hexdigest())
                    prior_bodies = {body_identity(s) for s in gateway.steps[:reconsidered_at_sources]}
                    new_body = any(body_identity(s) is not None and body_identity(s) not in prior_bodies
                                   for s in gateway.steps[reconsidered_at_sources:])
                    if not new_body:
                        gaps = outstanding_gaps
                attempted_finals[-1]['reported_evidence_gaps'] = gaps
                if gaps:
                    if (not reconsidered and tool_count < source_call_limit
                            and turn_index + 1 < MAX_SPARK_TURNS):
                        reconsidered = True
                        reconsidered_at_sources = len(gateway.steps)
                        outstanding_gaps = gaps
                        # The raw assistant answer already remains in history.
                        # No source identifier, legal conclusion or gap prose is
                        # promoted into this application instruction.
                        messages.append({'role': 'developer', 'content':
                            'Your attempted final answer explicitly reports missing retrieved evidence. '
                            'Reconsider that evidence gap once within the remaining source and model limits. '
                            'Use a relevant supplied tool if useful, or give an explicitly limited final answer. '
                            'Do not invent evidence or claim a gap is closed merely to finish.'})
                        state = 'turn_limit'
                        final = ''
                        continue
                    if state == 'complete':
                        state = 'admitted_evidence_gap'
            if state == 'complete' and authority_notice_conflict(final, gateway.steps):
                attempted_finals[-1]['authority_notice_conflict'] = True
                if not authority_reconsidered and turn_index + 1 < MAX_SPARK_TURNS:
                    authority_reconsidered = True
                    messages.append({'role':'developer','content':
                        'There is a potential conflict between your description of authority and the opened opinion citation notice. '
                        'Re-read that actual source notice and revise once, preserving its stated limits and distinguishing permission to cite from precedential weight. '
                        'Resolve from supplied evidence or state the uncertainty. Do not infer a legal status from a classifier label.'})
                    state = 'turn_limit'
                    final = ''
                    continue
                state = 'authority_notice_conflict'
            if state == 'complete' and length_bounds and not length_bounds[0] <= note_word_count(final) <= length_bounds[1]:
                if not length_revised and turn_index + 1 < MAX_SPARK_TURNS:
                    length_revised = True
                    messages.append({'role':'developer', 'content':
                        f'The attempted final answer is outside the requested {length_bounds[0]}–{length_bounds[1]} word range. Aim for about {(length_bounds[0]+length_bounds[1])//2} words to leave room for source notes. '
                        'Revise once using already opened evidence; no additional retrieval is needed. '
                        'Keep material qualifications and source attribution accurate. Count the note body and source notes; a short standalone title is separate. '
                        'Do not shorten quotations by altering their words, drop material limits, or invent support.'})
                    state = 'turn_limit'
                    final = ''
                    continue
                state = 'answer_length'
            if (state == 'complete' and not quote_format_revised
                    and turn_index + 1 < MAX_SPARK_TURNS
                    and re.search(r'^\s*>\s*\S', final, re.MULTILINE)
                    and quote_failures(final, [s.result for s in gateway.steps],
                                       extra=[DISCLAIMER, CASELAW_CATCH])):
                quote_format_revised = True
                messages.append({'role': 'developer', 'content':
                    'The attempted answer contains an unverified blockquote. Revise once using only '
                    'the evidence already opened. Present your synthesis as plain paraphrase, without '
                    'blockquote or quotation formatting; retain material source qualifications and '
                    'research limits. Do not invent support or silently change the legal conclusion. '
                    'No additional retrieval is needed. Any remaining quotation failure will withhold the answer.'})
                state = 'turn_limit'
                final = ''
                continue
            break
        if tool_count + len(calls) > source_call_limit:
            state = "tool_limit"
            break
        for call in calls:
            try:
                payload = await gateway.invoke(call["name"], call["arguments"])
            except CreditNotReady:
                state = "credit_limit"
                break
            except (httpx.HTTPError, TimeoutError):
                state = "source_error"
                break
            tool_count += 1
            encoded = json.dumps(payload, default=str)
            if len(encoded) > MAX_SOURCE_CHARS:
                state = "source_limit"
                break
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": encoded,
                }
            )
        if state in {"source_limit", "source_error", "credit_limit"}:
            break
    catch = None
    for step in gateway.steps:
        if step.tool == "ic_resolve_citation":
            catch = _missing_catch(step.result) or catch
        if step.tool == "ic_get_versions":
            catch = _versions_catch(step.result) or catch
    if state != "complete":
        reason = {
            "turn_limit": "The bounded research-turn limit was reached before a final answer.",
            "credit_limit": "The credit gate stopped further model requests; retrieved sources are retained.",
            "transport_error": "A model transport failure stopped research; sources and uncertain spend reservations are retained. No retry ran.",
            "invalid_response": "An invalid model response stopped research; retrieved sources and uncertain spend reservations are retained. No retry ran.",
            "source_error": "A source transport failure stopped research; previously retrieved sources are retained. No retry ran.",
            "missing_required_sources": "The requested source evidence is incomplete: " + ", ".join(build_research_state(question, gateway.steps, source_call_limit)["missing_evidence"]) + ". Retrieved sources and the limited model answer are retained.",
            "authority_notice_conflict": "The model description conflicts with an opened opinion citation notice after bounded reconsideration. Authority weight remains unresolved; the limited answer is retained.",
            "answer_length": "The model answer did not meet the requested word range after bounded revision. The limited answer is retained.",
            "admitted_evidence_gap": "The model explicitly reports missing retrieved evidence. Source-category checks do not establish substantive coverage. The limited answer is retained.",
            "no_evidence": "No full source body was retrieved; search leads alone cannot support a completed legal answer.",
            "tool_limit": "The bounded tool-call limit was reached before a final answer.",
            "source_limit": "A source exceeded the delivery limit; it was not silently truncated.",
            "context_limit": "The accumulated sources exceeded the bounded context limit.",
            "empty_answer": "The model returned no final answer.",
            "output_limit": "The model reached its output limit before finishing the answer.",
            "model_incomplete": "The model did not report a successfully completed answer.",
        }[state]
        catch = " ".join(filter(None, [catch, reason]))
        final = ("Research incomplete. " + reason + "\n\n" + final if state in {"missing_required_sources", "admitted_evidence_gap", "answer_length", "authority_notice_conflict"}
                 else "Research incomplete. " + reason + " Review the retrieved sources; no completed legal conclusion is shown.")
    summary = final.strip() or DISCLAIMER
    warning_present = all(re.search(pattern, summary, re.I) for pattern in (
        r'unofficial\s+copy', r'verify[^\n]*official\s+source',
        r'not\s+legal\s+advice', r'not\s+a\s+citator'))
    if not warning_present:
        summary = f"{summary}\n\n{DISCLAIMER}"
    if catch and catch not in summary:
        summary = f"{summary}\n\n{catch}"
    observed = build_research_state(question, gateway.steps, source_call_limit,
                                    attempted_finals=attempted_finals,
                                    gap_reconsideration_used=reconsidered)
    return summary, catch, state, observed


async def research_spark(
    question: str,
    *,
    as_of: str | None = None,
    url: str = DEFAULT_MCP_URL,
    turn=None,
    call_tool=None,
    source_call_limit: int | None = None,
) -> TurnResult:
    if turn is None and not spark_ready():
        raise CreditNotReady("MODEL_API_KEY is unset")
    turn_fn = turn or spark_turn
    limit = source_limit(question, source_call_limit)
    if call_tool is not None:
        gateway = LawGateway(call_tool=call_tool)
        summary, catch, state, observed = await _spark_loop(question, as_of=as_of, gateway=gateway, turn=turn_fn, source_call_limit=limit)
        result = TurnResult(
            question=question,
            mode="spark",
            planner="muse-spark-1.3",
            found=any(
                step.tool in {"ic_get_section", "case_get", "ic_get_companion"} and step.result.get("found")
                for step in gateway.steps
            ),
            catch=catch,
            summary=summary,
            disclaimer=DISCLAIMER,
            complete=state == "complete",
            completion_state=state,
        )
        finished = _finish(result, gateway)
        finished.research_state = observed
        finished.opened_sources = opened_sources(gateway.steps)
        finished.spark_ready = spark_ready()
        return finished
    async with LiveMcp(url) as mcp:
        gateway = LawGateway(call_tool=mcp.call)
        summary, catch, state, observed = await _spark_loop(question, as_of=as_of, gateway=gateway, turn=turn_fn, source_call_limit=limit)
        result = TurnResult(
            question=question,
            mode="spark",
            planner="muse-spark-1.3",
            found=any(
                step.tool in {"ic_get_section", "case_get", "ic_get_companion"} and step.result.get("found")
                for step in gateway.steps
            ),
            catch=catch,
            summary=summary,
            disclaimer=DISCLAIMER,
            complete=state == "complete",
            completion_state=state,
        )
        finished = _finish(result, gateway)
        finished.research_state = observed
        finished.opened_sources = opened_sources(gateway.steps)
        finished.spark_ready = True
        finished.tool_names = mcp.tool_names
        return finished


async def research(
    question: str,
    *,
    as_of: str | None = None,
    mode: str = "auto",
    url: str = DEFAULT_MCP_URL,
) -> TurnResult:
    chosen = mode
    if mode == "auto":
        chosen = "spark" if spark_ready() else "fixture"
    if chosen == "spark":
        return await research_spark(question, as_of=as_of, url=url)
    return await research_fixture(question, as_of=as_of, url=url)


def stamp() -> str:
    return datetime.now(UTC).isoformat()
