"""Explicitly scripted rehearsal over live public sources; never calls Muse."""
from app.law_gateway import DEFAULT_MCP_URL, LiveMcp
from app.research import research_spark
from app.spark_replay import replay_turn, text_message, tool_message

DEMO_QUESTION = "Can an Indiana tenant lose possession before a jury hears the eviction case? What hearing protections come first?"
DEMO_STEPS = [
    ("ic_get_companion", {"doc_id": "constitution-2026", "page": 3}),
    ("ic_get_companion", {"doc_id": "court-rules-2026-small-claims", "page": 6}),
    ("ic_get_companion", {"doc_id": "court-rules-2026-small-claims", "page": 7}),
    ("ic_get_companion", {"doc_id": "court-rules-2026-trial", "page": 114}),
    *[("ic_get_section", {"section_id": sid, "as_of": "2026-11-02"})
      for sid in ("32-30-3-2", "32-30-3-5", "32-30-3-6")],
    ("case_get", {"cluster_id": "2100393"}),
    ("case_get", {"cluster_id": "852407"}),
    ("case_get", {"cluster_id": "incourts-1106156996"}),
]
DEMO_ANSWER = """Rehearsal — prepared narration over freshly retrieved sources. No live Muse answer.

Yes, preliminary possession can precede the jury's final merits decision. That does not eliminate the tenant's opportunity to defend.

1. Indiana Constitution, Article 1, §20 protects the civil jury right. Small Claims Rule 4(C) governs a timely written demand and transfer; Trial Rule 38 supplies the historical law/equity framework. These provisions do not require a jury at every preliminary stage.

2. IC 32-30-3-2 describes the affidavit-triggered show-cause hearing, notice, and opportunity to submit affidavits and testimony. Section 5 makes the possession determination preliminary pending final adjudication. Section 6 requires the plaintiff's approved undertaking before an order other than final judgment. Do not confuse the statutory hearing clock with the jury-demand clock.

3. Bishop v. Housing Authority of South Bend, 920 N.E.2d 772 (Ind. Ct. App. 2010), distinguishes preliminary possession from the ultimate jury determination. Morton v. Ivacic, 898 N.E.2d 1196 (Ind. 2008), reverses because the tenant lacked a sufficient opportunity to defend. A preliminary hearing is still a hearing with meaningful protections.

Research catch: Morton's disposition metadata was observed as affirmed, while the Supreme Court opinion reverses. The earlier appellate affirmance and a footnote affirming other issues must not replace the Supreme Court's actual disposition. Its state constitutional claims were waived, not decided on their merits. Bishop's unlabeled classifier is missing information, not a contradictory judgment.

Johnson v. Housing Authority of South Bend (2023) distinguishes final possession from preliminary possession and limits blanket affidavit/bond claims; it reversed a final possession order for failure to hear defenses. Its public-housing-specific federal lease obligations do not automatically apply to every landlord.

This is an ordinary-ejectment procedural example, not every eviction route. Final possession, emergency procedures, and public-housing requirements need separate analysis. The Code is a dated unofficial compilation; present-day rules do not establish historical wording. Subsequent-history review is incomplete. Inspect the source cards and trace.
"""


async def rehearse_eviction(question=DEMO_QUESTION, *, call_tool=None, url=DEFAULT_MCP_URL):
    if question != DEMO_QUESTION:
        raise ValueError("The scripted rehearsal accepts only its displayed public example.")
    if call_tool is None:
        async with LiveMcp(url) as mcp:
            return await rehearse_eviction(question, call_tool=mcp.call)

    async def checked(name, args):
        result = await call_tool(name, args)
        if result.get("found") is not True or not result.get("text"):
            raise ValueError("Rehearsal source unavailable; prepared conclusion withheld.")
        return result

    script = [tool_message(name, args, str(i)) for i, (name, args) in enumerate(DEMO_STEPS)]
    script.append(text_message(DEMO_ANSWER))
    result = await research_spark(question, turn=replay_turn(script), call_tool=checked)
    result.mode = "rehearsal"
    result.planner = "scripted rehearsal; no Muse inference"
    result.spark_ready = False
    return result
