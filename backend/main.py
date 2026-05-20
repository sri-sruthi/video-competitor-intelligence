"""
main.py
FastAPI entry point for the Video Competitor Intelligence tool.
"""

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from sse_starlette.sse import EventSourceResponse
from datetime import datetime
import asyncio, json, uuid, os, logging, re

from backend.services.youtube_service import YouTubeService
from backend.services.analytics_service import AnalyticsService
from backend.services.ai_service import AIService
from backend.services.seo_service import SEOService
from backend.services.pptx_service import PPTXService
from backend.config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Video Competitor Intelligence", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup_event():
    os.makedirs("outputs", exist_ok=True)


# Instantiate services at module level
youtube_service = YouTubeService(api_key=settings.YOUTUBE_API_KEY)
analytics_service = AnalyticsService()
ai_service = AIService(
    api_key=settings.GEMINI_API_KEY,
    groq_api_key=settings.GROQ_API_KEY,
)
seo_service = SEOService(serpapi_api_key=settings.SERPAPI_API_KEY)
pptx_service = PPTXService()


def fallback_executive_summary(companies: list[str], rpi_scores: dict) -> str:
    if not companies:
        return "Executive summary unavailable. No companies were processed successfully."

    ranked = sorted(companies, key=lambda c: rpi_scores.get(c, {}).get("rank", 999))
    top_company = ranked[0]
    top_rpi = rpi_scores.get(top_company, {}).get("rpi_score", 0.0)
    return (
        f"This summary is based on the computed report metrics for the selected peer set. "
        f"{top_company} currently leads the benchmark set with a Video Marketing Health Score of {top_rpi:.1f}. "
        "Use the rest of the report to see whether that lead comes from audience response, publishing discipline, discovery setup, or stronger coverage of buyer needs. "
        "Treat funnel classification as a directional content signal based on video metadata, not as a direct conversion measurement."
    )


def fallback_gap_analysis(gap_topics: list[str]) -> str:
    if not gap_topics:
        return (
            "The peer set does not show one obvious uncovered theme, but there is still strategic whitespace in how buyer-stage content is packaged, sequenced, and explained. "
            "Use the opportunities on this slide as test candidates rather than assuming the market is saturated."
        )
    top_topics = ", ".join(gap_topics[:3])
    return (
        "The AI-written gap narrative was unavailable for this run. "
        f"Initial whitespace signals were identified around: {top_topics}. "
        "Use these themes as strategic tests that could strengthen discoverability, buyer education, or proof content."
    )


def fallback_action_plan(
    target_company: str,
    cadence_days: float,
    planning_context: dict | None = None,
) -> str:
    planning_context = planning_context or {}
    top_length = planning_context.get("best_performing_length", "best-performing")
    whitespace = ", ".join(planning_context.get("whitespace_topics", [])[:2]) or "the strongest whitespace theme"
    seo_score = planning_context.get("seo_score", 0.0)
    return (
        f"Week 1–2: audit {target_company}'s current mix, choose one buyer-stage gap to fix first, and brief the next 3 videos around {whitespace}. "
        f"Month 1: publish at least one proof-led asset while moving toward a steadier cadence than the current {cadence_days:.1f}-day average and keeping packaging quality above the current SEO score of {seo_score:.1f}/100. "
        f"Month 2–3: turn the strongest early signal into a repeatable {top_length} mini-series, track views-per-day and engagement by format, and refine future topics using the whitespace and SEO sections."
    )


def recommendations_need_fallback(recommendations: list[dict]) -> bool:
    if not recommendations:
        return True
    generic_title_markers = {
        "optimize video length",
        "improve upload consistency",
        "diversify video formats",
        "enhance seo strategy",
        "refine funnel distribution strategy",
    }
    low_quality_count = 0
    for rec in recommendations[:5]:
        title = str(rec.get("title", "")).strip().lower()
        action = str(rec.get("action", "")).strip().lower()
        why_this_matters = str(rec.get("why_this_matters", "")).strip()
        business_impact = str(rec.get("business_impact", "")).strip()
        supporting_evidence = str(rec.get("supporting_evidence", "")).strip()
        if (
            title.startswith("recommendation ")
            or action == "see full report for details."
            or title in generic_title_markers
            or len(action.split()) < 6
            or not why_this_matters
            or not business_impact
            or not supporting_evidence
        ):
            low_quality_count += 1
    return low_quality_count >= 2 or len(recommendations) < 5


def sanitize_recommendations_for_web(recommendations: list[dict]) -> list[dict]:
    cleaned: list[dict] = []
    for rec in recommendations:
        title = " ".join(str(rec.get("title", "")).split()).replace("...", ".").strip()
        action = " ".join(str(rec.get("action", "")).split()).replace("...", ".").strip()
        rationale = " ".join(
            str(rec.get("data_rationale") or rec.get("supporting_evidence") or "").split()
        ).replace("...", ".").strip()
        why_this_matters = " ".join(str(rec.get("why_this_matters", "")).split()).replace("...", ".").strip()
        business_impact = " ".join(str(rec.get("business_impact", "")).split()).replace("...", ".").strip()
        success_kpi = " ".join(str(rec.get("success_kpi", "")).split()).replace("...", ".").strip()
        supporting_evidence = " ".join(
            str(rec.get("supporting_evidence") or rationale).split()
        ).replace("...", ".").strip()
        impact = " ".join(
            str(rec.get("expected_impact") or business_impact).split()
        ).replace("...", ".").strip()

        lowered_impact = impact.lower()
        if (
            any(ch.isdigit() for ch in impact)
            or "significantly" in lowered_impact
            or "guarantee" in lowered_impact
            or "reverse" in lowered_impact
            or "increase lead conversion rates" in lowered_impact
            or "click-through rates" in lowered_impact
        ):
            title_key = title.lower()
            if "seo" in title_key or "search" in title_key:
                impact = "Likely to improve discoverability and make the videos easier to navigate."
            elif "cadence" in title_key or "publish" in title_key or "consisten" in title_key:
                impact = "Likely to create more predictable audience expectations and steadier performance tracking."
            elif "conversion" in title_key or "bofu" in title_key or "funnel" in title_key:
                impact = "Likely to strengthen coverage for higher-intent viewers closer to a decision."
            elif "theme" in title_key or "trend" in title_key or "gap" in title_key:
                impact = "Likely to improve learning speed on whether the theme deserves repeat investment."
            else:
                impact = "Likely to improve content-market fit if execution stays consistent."

        cleaned.append(
            {
                **rec,
                "title": title.rstrip("."),
                "action": action.rstrip(".") + "." if action else "",
                "data_rationale": rationale.rstrip(".") + "." if rationale else "",
                "why_this_matters": why_this_matters.rstrip(".") + "." if why_this_matters else "",
                "business_impact": business_impact.rstrip(".") + "." if business_impact else "",
                "success_kpi": success_kpi.rstrip(".") + "." if success_kpi else "",
                "supporting_evidence": supporting_evidence.rstrip(".") + "." if supporting_evidence else "",
                "expected_impact": impact.rstrip(".") + "." if impact else "",
            }
        )
    return cleaned


def build_fallback_recommendations(
    target_company: str,
    company_row: dict,
    gap_topics: list[str],
    seo_score: float,
) -> list[dict]:
    dominant_format = str(
        company_row.get("dominant_format")
        or company_row.get("format_mix", {}).get("dominant_format", "mixed")
    ).replace("_", " ")
    funnel_label = company_row.get("funnel_label", "Balanced")
    recommendations: list[dict] = []

    if company_row.get("bofu_pct", 0.0) <= 12:
        recommendations.append(
            {
                "title": "Build a clearer proof and conversion layer",
                "action": (
                    f"Add at least one proof-led asset each month for {target_company}, such as a demo, case study, "
                    "comparison, or implementation story aimed at high-intent buyers"
                ),
                "data_rationale": (
                    f"The current funnel mix is {company_row.get('tofu_pct', 0):.1f}% awareness / "
                    f"{company_row.get('mofu_pct', 0):.1f}% consideration / {company_row.get('bofu_pct', 0):.1f}% proof-focused content"
                ),
                "why_this_matters": "Awareness content can create reach, but without proof content the channel does less to help buyers validate the product late in the journey",
                "business_impact": "Better support for evaluation-stage viewers and a more complete path from discovery to decision",
                "success_kpi": "Increase the share of proof-led videos published and track views-per-day plus engagement on those assets",
                "supporting_evidence": (
                    f"{target_company} currently has only {company_row.get('bofu_pct', 0):.1f}% proof-focused coverage in the recent sample"
                ),
                "expected_impact": "Stronger conversion-intent coverage and a more balanced content path",
                "priority": "high",
            }
        )

    if company_row.get("consistency_score", 0.0) < 55:
        recommendations.append(
            {
                "title": "Stabilize the publishing rhythm",
                "action": (
                    f"Move from the current {company_row.get('mean_gap_days', 0.0):.1f}-day average gap to a planned weekly or bi-weekly cadence for the next 60 days"
                ),
                "data_rationale": (
                    f"Consistency is currently {company_row.get('consistency_score', 0.0):.1f}/100, which limits repeat audience habits"
                ),
                "why_this_matters": "Predictable publishing makes it easier for the audience to build return-viewing habits and for the team to compare performance cleanly",
                "business_impact": "More stable measurement and better odds of compounding learnings from repeated formats or themes",
                "success_kpi": "Reduce variance in upload gaps and improve cadence confidence over the next 8 weeks",
                "supporting_evidence": (
                    f"The current cadence score is {company_row.get('consistency_score', 0.0):.1f}/100 with an average gap of {company_row.get('mean_gap_days', 0.0):.1f} days"
                ),
                "expected_impact": "More reliable audience expectations and steadier performance compounding",
                "priority": "high",
            }
        )

    if company_row.get("format_mix", {}).get("format_diversity_score", 0.0) < 40:
        recommendations.append(
            {
                "title": "Broaden the format mix",
                "action": (
                    f"Reduce over-reliance on {dominant_format} content by testing tutorials, case studies, customer proof, "
                    "or webinar cut-downs"
                ),
                "data_rationale": (
                    f"Format diversity is only {company_row.get('format_mix', {}).get('format_diversity_score', 0.0):.1f}/100"
                ),
                "why_this_matters": "An overly narrow format mix can trap the team in one audience need and reduce learning about what different buyers respond to",
                "business_impact": "Better coverage of different viewer intents without abandoning the format that already performs best",
                "success_kpi": "Increase the number of distinct formats used in the next 6 to 8 videos",
                "supporting_evidence": (
                    f"{dominant_format.title()} appears dominant while format diversity is only {company_row.get('format_mix', {}).get('format_diversity_score', 0.0):.1f}/100"
                ),
                "expected_impact": "Lower fatigue risk and better coverage of different audience intents",
                "priority": "medium",
            }
        )

    if seo_score < 75:
        recommendations.append(
            {
                "title": "Improve packaging for search and click-through",
                "action": "Tighten title structure, strengthen description depth, and add timestamps where they genuinely improve navigation",
                "data_rationale": f"The current SEO score is {seo_score:.1f}/100, leaving room to improve discoverability",
                "why_this_matters": "Better packaging gives strong ideas a fairer chance to be found and understood before the viewer even clicks",
                "business_impact": "More qualified discovery and better navigation for educational or demo-led videos",
                "success_kpi": "Raise the discovery score and improve views-per-day on newly packaged videos",
                "supporting_evidence": f"The current SEO score is {seo_score:.1f}/100.",
                "expected_impact": "Higher qualified discovery and easier content navigation for viewers",
                "priority": "medium",
            }
        )

    if gap_topics:
        recommendations.append(
            {
                "title": "Test one whitespace theme immediately",
                "action": f"Pilot a content theme around {gap_topics[0]} and measure views-per-day plus engagement within the first two weeks",
                "data_rationale": "The topic-cluster analysis found at least one under-covered theme across the peer set",
                "why_this_matters": "A focused whitespace test helps the team learn whether there is an underserved demand pocket before committing to a full series",
                "business_impact": "Faster learning on whether a new theme can become a repeatable content pillar",
                "success_kpi": "Track first-14-day views-per-day, engagement rate, and click-through on the test video",
                "supporting_evidence": f"One of the clearest whitespace themes in the peer set is {gap_topics[0]}.",
                "expected_impact": "Faster learning on whether the identified whitespace can become a repeatable content pillar",
                "priority": "medium",
            }
        )

    recommendations.append(
        {
            "title": "Make the channel more useful to a defined buyer stage",
            "action": "Choose one audience stage to strengthen first and map the next 6 videos so each one clearly supports discovery, evaluation, or proof",
            "data_rationale": f"The current content mix is labelled {funnel_label}.",
            "why_this_matters": "When every video is trying to serve every audience, the channel becomes harder to interpret and harder to optimize",
            "business_impact": "Clearer content planning and a more deliberate path from reach to revenue support",
            "success_kpi": "Review the next 6 planned videos and confirm each one has an explicit buyer-stage role",
            "supporting_evidence": f"The recent sample currently reads as {funnel_label}.",
            "expected_impact": "Stronger editorial clarity and better sequencing across the buyer journey",
            "priority": "medium",
        }
    )

    recommendations.append(
        {
            "title": "Turn winning performance patterns into a repeatable series",
            "action": "Take the best-performing length or format signal from the recent sample and turn it into a 3-part repeatable series with a shared structure",
            "data_rationale": (
                f"The best-performing length currently reads as {company_row.get('best_performing_length', 'mixed')} and the dominant format is {dominant_format}"
            ),
            "why_this_matters": "One-off hits are useful, but repeatable series design is what turns isolated wins into a scalable editorial habit",
            "business_impact": "Faster learning loops and clearer evidence on what the audience repeatedly rewards",
            "success_kpi": "Compare the next three related videos on engagement rate, views-per-day, and retention proxies",
            "supporting_evidence": (
                f"The recent sample already points toward {company_row.get('best_performing_length', 'mixed')} content and {dominant_format} as existing signals."
            ),
            "expected_impact": "More reliable learning from repeated creative patterns instead of disconnected experiments",
            "priority": "medium",
        }
    )

    deduped: list[dict] = []
    seen_titles: set[str] = set()
    for rec in recommendations:
        key = str(rec.get("title", "")).strip().lower()
        if not key or key in seen_titles:
            continue
        seen_titles.add(key)
        deduped.append(rec)
        if len(deduped) == 5:
            break

    while len(deduped) < 5:
        deduped.append(
            {
                "title": "Protect what already works while testing one deliberate change",
                "action": f"Keep the strongest elements of {target_company}'s current strategy while testing one new theme and one new format next month",
                "data_rationale": f"The current funnel label is {funnel_label}, so the next step is targeted experimentation rather than a full reset",
                "why_this_matters": "A measured test plan is safer than changing every variable at once",
                "business_impact": "Cleaner learning with lower execution risk",
                "success_kpi": "Track one primary metric for the new theme and compare it with the current baseline",
                "supporting_evidence": f"The recent sample suggests targeted experimentation is more appropriate than a wholesale reset for {target_company}.",
                "expected_impact": "Safer iteration with clearer learning signals",
                "priority": "medium",
            }
        )

    return deduped[:5]


def sanitize_ai_text(text: str) -> str:
    cleaned = " ".join(str(text or "").split()).strip()
    return cleaned.replace("...", ".")


def sanitize_structured_ai_text(text: str) -> str:
    raw = str(text or "").replace("\r", "\n")
    lines = [line.strip() for line in raw.split("\n")]
    normalized = "\n".join(line for line in lines if line)
    normalized = re.sub(r"\s+\n", "\n", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    normalized = normalized.replace("...", ".").strip()
    return normalized


def normalize_executive_summary_text(text: str) -> str:
    cleaned = sanitize_structured_ai_text(text)
    if not cleaned:
        return ""

    normalized = re.sub(r"\s+-\s+", "\n- ", cleaned)
    normalized = re.sub(r"\s+(What this means:)", r"\n\1", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized).strip()
    return normalized


def action_plan_needs_fallback(text: str) -> bool:
    cleaned = str(text or "").strip().lower()
    if not cleaned:
        return True
    markers = [
        "[client company name]",
        "[your name/agency name]",
        "### strategic video marketing action plan",
        "prepared by:",
    ]
    return any(marker in cleaned for marker in markers)


def clean_gap_topics_for_reporting(service: AnalyticsService, raw_topics: list[str]) -> list[str]:
    cleaned_topics: list[str] = []
    for label in raw_topics:
        canonical = service._canonicalize_topic_label(str(label or ""))
        if not canonical:
            continue
        if not _is_client_safe_topic_label(service, canonical):
            continue
        simplified = canonical
        if simplified and simplified not in cleaned_topics:
            cleaned_topics.append(simplified)
    return cleaned_topics


def _is_client_safe_topic_label(service: AnalyticsService, label: str) -> bool:
    raw = str(label or "").strip()
    if not raw:
        return False
    if service._strategic_theme_hits(raw):
        return True

    lowered = raw.lower()
    banned_tokens = {
        "yum", "vidico", "ninja", "explain", "duck", "demo", "mypromovideos",
        "salesforce", "mailchimp", "monday", "wistia", "script", "great",
        "time", "ads", "ad", "don", "high",
    }
    words = [word.lower() for word in re.findall(r"[a-zA-Z][a-zA-Z&+-]*", lowered)]
    if not words:
        return False
    if any(word in banned_tokens for word in words):
        return False
    substantial = [word for word in words if len(word) >= 4]
    if len(substantial) < 2:
        return False
    parts = [part.strip() for part in re.split(r"[\/|•]", raw) if part.strip()]
    single_word_parts = [
        part for part in parts
        if len(re.findall(r"[A-Za-z]+", part)) <= 1
    ]
    if len(parts) >= 2 and len(single_word_parts) == len(parts):
        return False
    return True


def filter_client_safe_opportunity_scores(
    service: AnalyticsService,
    opportunity_scores: list[dict],
) -> list[dict]:
    filtered: list[dict] = []
    seen_topics: set[str] = set()
    for opp in opportunity_scores:
        canonical_topic = service._canonicalize_topic_label(str(opp.get("topic", "") or ""))
        if not canonical_topic or not _is_client_safe_topic_label(service, canonical_topic):
            continue
        key = canonical_topic.lower()
        if key in seen_topics:
            continue
        seen_topics.add(key)
        filtered.append({**opp, "topic": canonical_topic})
    return filtered


def build_fallback_opportunity_scores(
    target_company: str,
    target_data: dict,
    processed_data: dict[str, dict],
) -> list[dict]:
    peer_rows = [row for name, row in processed_data.items() if name != target_company]
    peer_avg_bofu = (
        sum(row.get("bofu_pct", 0.0) for row in peer_rows) / len(peer_rows)
        if peer_rows else 15.0
    )
    peer_avg_tofu = (
        sum(row.get("tofu_pct", 0.0) for row in peer_rows) / len(peer_rows)
        if peer_rows else 20.0
    )
    seo_score = float(target_data.get("seo_score", 0.0) or 0.0)
    timestamps_pct = float(
        target_data.get("seo_full", {}).get("breakdown", {}).get("has_timestamps_pct", 0.0) or 0.0
    )
    format_diversity = float(target_data.get("format_diversity_score", 0.0) or 0.0)
    dominant_format = str(target_data.get("dominant_format", "current core format")).replace("_", " ")
    best_length = str(target_data.get("best_performing_length", "short"))

    opportunities = [
        {
            "topic": "Proof-led customer validation",
            "opportunity_score": round(min(96.0, 70.0 + max(peer_avg_bofu - target_data.get("bofu_pct", 0.0), 0.0) * 1.6), 1),
            "trend_interest": 62.0,
            "momentum_score": 58.0,
            "scarcity_score": round(min(100.0, 55.0 + max(peer_avg_bofu - target_data.get("bofu_pct", 0.0), 0.0) * 2.2), 1),
            "recommendation_type": "Buyer-stage coverage gap",
            "opportunity_brief": "The client has limited decision-stage proof content relative to peers.",
            "supporting_evidence": (
                f"{target_company} has {target_data.get('bofu_pct', 0.0):.1f}% proof-stage coverage versus a peer average of {peer_avg_bofu:.1f}%."
            ),
            "suggested_experiment": "Test one customer proof, case-study, or objection-handling video within the next publishing cycle.",
            "signal_to_watch": "Track views-per-day, completion quality, and whether higher-intent calls-to-action improve.",
            "fallback_used": True,
            "trend_source": "heuristic",
        },
        {
            "topic": "Search-led educational explainers",
            "opportunity_score": round(min(92.0, 68.0 + max(75.0 - seo_score, 0.0) * 0.8 + (12.0 if timestamps_pct == 0 else 0.0)), 1),
            "trend_interest": 66.0,
            "momentum_score": 61.0,
            "scarcity_score": round(min(100.0, 52.0 + max(75.0 - seo_score, 0.0)), 1),
            "recommendation_type": "Discovery and packaging gap",
            "opportunity_brief": "The channel can likely earn more qualified discovery from clearer search-led education.",
            "supporting_evidence": (
                f"The current SEO score is {seo_score:.1f}/100 and timestamps are used on {timestamps_pct:.1f}% of recent videos."
            ),
            "suggested_experiment": f"Publish one {best_length}-form explainer built around a concrete buyer question and stronger navigation cues.",
            "signal_to_watch": "Monitor first-14-day discovery, click-through quality, and organic views-per-day on the test asset.",
            "fallback_used": True,
            "trend_source": "heuristic",
        },
        {
            "topic": "Format variety beyond current core format",
            "opportunity_score": round(min(88.0, 64.0 + max(72.0 - format_diversity, 0.0) * 0.7 + max(peer_avg_tofu - target_data.get("tofu_pct", 0.0), 0.0) * 0.5), 1),
            "trend_interest": 57.0,
            "momentum_score": 54.0,
            "scarcity_score": round(min(100.0, 48.0 + max(72.0 - format_diversity, 0.0)), 1),
            "recommendation_type": "Format diversification gap",
            "opportunity_brief": "The current mix leans heavily on one format, which limits coverage of different buyer needs.",
            "supporting_evidence": (
                f"The dominant format is {dominant_format} and format diversity is {format_diversity:.1f}/100."
            ),
            "suggested_experiment": f"Pair one new educational or proof-led format with the existing {dominant_format} pattern to test whether engagement broadens.",
            "signal_to_watch": "Compare engagement rate and repeat-view response between the new format and the current dominant format.",
            "fallback_used": True,
            "trend_source": "heuristic",
        },
    ]

    return opportunities


def build_fallback_gap_analysis_from_opportunities(target_company: str, opportunity_scores: list[dict]) -> str:
    if not opportunity_scores:
        return (
            "The peer set does not show one obvious uncovered theme, but there is still strategic whitespace in how buyer-stage content is packaged, sequenced, and explained. "
            "Use the opportunities on this slide as test candidates rather than assuming the market is saturated."
        )
    top = opportunity_scores[:3]
    summary = "; ".join(
        f"{item.get('topic', 'Opportunity')} ({item.get('opportunity_score', 0):.0f}/100)"
        for item in top
    )
    return (
        f"Even without one clean uncovered cluster, {target_company} still has strategic whitespace worth testing. "
        f"The clearest opportunities in this sample are {summary}. "
        "These are not claims of guaranteed demand; they are evidence-backed experiments designed to improve discovery, buyer education, or proof content."
    )


def build_slide_interpretation_context(
    companies: list[str],
    company_data: dict[str, dict],
    rpi_scores: dict[str, dict],
    seo_scores: dict[str, dict],
    topic_clusters: dict,
    opportunity_scores: list[dict],
    recommendations: list[dict],
    target_company: str,
    action_plan: str,
) -> dict:
    ranked = sorted(companies, key=lambda c: rpi_scores.get(c, {}).get("rank", 999))
    leader = ranked[0] if ranked else ""
    laggard = ranked[-1] if ranked else ""
    target_row = company_data.get(target_company, {})
    top_gap = opportunity_scores[0] if opportunity_scores else {}
    return {
        "slide_02": {
            "title": "Executive brief",
            "target_company": target_company,
            "target_rpi": rpi_scores.get(target_company, {}).get("rpi_score", 0.0),
            "leader": leader,
            "leader_rpi": rpi_scores.get(leader, {}).get("rpi_score", 0.0),
            "target_engagement": target_row.get("avg_engagement_rate", 0.0),
            "target_consistency": target_row.get("consistency_score", 0.0),
        },
        "slide_03": {
            "title": "Channel overview",
            "target_company": target_company,
            "channels": {
                company: {
                    "subscriber_count": company_data.get(company, {}).get("subscriber_count", 0),
                    "video_count": company_data.get(company, {}).get("video_count", 0),
                    "consistency_score": company_data.get(company, {}).get("consistency_score", 0.0),
                }
                for company in companies
            },
        },
        "slide_04": {
            "title": "Video marketing health score",
            "target_company": target_company,
            "rpi": {
                company: {
                    "rank": rpi_scores.get(company, {}).get("rank", 999),
                    "score": rpi_scores.get(company, {}).get("rpi_score", 0.0),
                }
                for company in companies
            },
        },
        "slide_05": {
            "title": "Upload cadence and consistency",
            "target_company": target_company,
            "cadence": {
                company: {
                    "mean_gap_days": company_data.get(company, {}).get("mean_gap_days", 0.0),
                    "consistency_score": company_data.get(company, {}).get("consistency_score", 0.0),
                    "cadence_confidence": company_data.get(company, {}).get("cadence_confidence", ""),
                }
                for company in companies
            },
        },
        "slide_06": {
            "title": "Audience journey coverage",
            "target_company": target_company,
            "funnel": {
                company: {
                    "label": company_data.get(company, {}).get("funnel_label", "—"),
                    "tofu_pct": company_data.get(company, {}).get("tofu_pct", 0.0),
                    "mofu_pct": company_data.get(company, {}).get("mofu_pct", 0.0),
                    "bofu_pct": company_data.get(company, {}).get("bofu_pct", 0.0),
                    "confidence": company_data.get(company, {}).get("funnel_confidence", ""),
                }
                for company in companies
            },
        },
        "slide_07": {
            "title": "Engagement trend",
            "target_company": target_company,
            "engagement": {
                company: {
                    "avg_engagement_rate": company_data.get(company, {}).get("avg_engagement_rate", 0.0),
                    "engagement_trend_slope": company_data.get(company, {}).get("engagement_trend_slope", 0.0),
                }
                for company in companies
            },
        },
        "slide_08": {
            "title": "Top performing videos",
            "target_company": target_company,
            "top_videos": {
                company: [
                    {
                        "title": video.get("title", ""),
                        "view_count": video.get("view_count", 0),
                        "views_per_day": video.get("views_per_day", 0.0),
                        "engagement_rate": video.get("engagement_rate", 0.0),
                    }
                    for video in company_data.get(company, {}).get("top_videos", [])[:2]
                ]
                for company in companies
            },
        },
        "slide_09": {
            "title": "Content topics and themes",
            "target_company": target_company,
            "company_theme_labels": topic_clusters.get("company_theme_labels", {}),
            "company_coverage": topic_clusters.get("company_coverage", {}),
            "gap_topics": topic_clusters.get("gap_topics", [])[:5],
        },
        "slide_10": {
            "title": "Content format performance",
            "target_company": target_company,
            "length": {
                company: {
                    "best_performing_length": company_data.get(company, {}).get("best_performing_length", "—"),
                    "short_er": company_data.get(company, {}).get("short", {}).get("avg_engagement_rate", 0.0),
                    "medium_er": company_data.get(company, {}).get("medium", {}).get("avg_engagement_rate", 0.0),
                    "long_er": company_data.get(company, {}).get("long", {}).get("avg_engagement_rate", 0.0),
                }
                for company in companies
            },
        },
        "slide_11": {
            "title": "Discovery and search visibility",
            "target_company": target_company,
            "seo": {
                company: {
                    "seo_score": seo_scores.get(company, {}).get("seo_score", 0.0),
                    "timestamp_pct": seo_scores.get(company, {}).get("breakdown", {}).get("has_timestamps_pct", 0.0),
                    "description_depth": seo_scores.get(company, {}).get("breakdown", {}).get("description_depth", 0.0),
                }
                for company in companies
            },
        },
        "slide_12": {
            "title": "Strategic whitespace opportunities",
            "target_company": target_company,
            "opportunities": opportunity_scores[:3],
            "top_opportunity": top_gap,
        },
        "slide_13": {
            "title": "Priority moves - high",
            "target_company": target_company,
            "recommendations": [rec for rec in recommendations if str(rec.get("priority", "")).lower() == "high"][:3],
        },
        "slide_14": {
            "title": "Priority moves - medium",
            "target_company": target_company,
            "recommendations": [rec for rec in recommendations if str(rec.get("priority", "")).lower() != "high"][:3],
        },
        "slide_15": {
            "title": "Company growth scorecard",
            "target_company": target_company,
            "rank": rpi_scores.get(target_company, {}).get("rank", 999),
            "rpi_score": rpi_scores.get(target_company, {}).get("rpi_score", 0.0),
            "engagement": target_row.get("avg_engagement_rate", 0.0),
            "consistency": target_row.get("consistency_score", 0.0),
            "seo_score": seo_scores.get(target_company, {}).get("seo_score", 0.0),
            "leader": leader,
            "laggard": laggard,
        },
        "slide_16": {
            "title": "90-day action plan",
            "target_company": target_company,
            "mean_gap_days": target_row.get("mean_gap_days", 0.0),
            "best_performing_length": target_row.get("best_performing_length", ""),
            "top_whitespace_topic": str(top_gap.get("topic", "")),
            "action_plan": action_plan,
        },
    }


def build_fallback_slide_interpretations(
    companies: list[str],
    company_data: dict[str, dict],
    rpi_scores: dict[str, dict],
    seo_scores: dict[str, dict],
    topic_clusters: dict,
    opportunity_scores: list[dict],
    recommendations: list[dict],
    target_company: str,
) -> dict[str, str]:
    if not companies:
        return {}

    ranked = sorted(companies, key=lambda c: rpi_scores.get(c, {}).get("rank", 999))
    leader = ranked[0]
    laggard = ranked[-1]
    target_row = company_data.get(target_company, {})
    biggest = max(companies, key=lambda c: company_data.get(c, {}).get("subscriber_count", 0))
    steadiest = max(companies, key=lambda c: company_data.get(c, {}).get("consistency_score", 0.0))
    engagement_leader = max(companies, key=lambda c: company_data.get(c, {}).get("avg_engagement_rate", 0.0))
    top_video_company = max(
        companies,
        key=lambda c: max((video.get("view_count", 0) for video in company_data.get(c, {}).get("top_videos", [])), default=0),
    )
    top_video_views = max((video.get("view_count", 0) for video in company_data.get(top_video_company, {}).get("top_videos", [])), default=0)
    top_gap = opportunity_scores[0] if opportunity_scores else {}
    top_gap_label = str(top_gap.get("topic", "underserved theme")).split("/")[0].strip()
    top_gap_score = float(top_gap.get("opportunity_score", 0.0) or 0.0)
    theme_leader = max(companies, key=lambda c: len(topic_clusters.get("company_coverage", {}).get(c, [])))
    timestamp_zero = sum(
        1 for company in companies
        if seo_scores.get(company, {}).get("breakdown", {}).get("has_timestamps_pct", 0.0) == 0.0
    )
    return {
        "slide_02": (
            f"{leader} currently leads the peer set at {rpi_scores.get(leader, {}).get('rpi_score', 0.0):.1f}, while {target_company} is at {rpi_scores.get(target_company, {}).get('rpi_score', 0.0):.1f}. "
            "The biggest client takeaway is whether audience response, publishing discipline, or discovery setup is creating the gap."
        ),
        "slide_03": (
            f"{biggest} has the largest existing audience in this peer set, but {target_company} still has {company_data.get(target_company, {}).get('subscriber_count', 0):,} subscribers to build from. "
            "This slide matters because execution efficiency can still improve even when the audience base is smaller."
        ),
        "slide_04": (
            f"{leader} leads the health score at {rpi_scores.get(leader, {}).get('rpi_score', 0.0):.1f}, while {laggard} is lowest at {rpi_scores.get(laggard, {}).get('rpi_score', 0.0):.1f}. "
            "Use this score as a benchmark summary, then use the next slides to see which operating levers are driving the difference."
        ),
        "slide_05": (
            f"{steadiest} has the strongest consistency score at {company_data.get(steadiest, {}).get('consistency_score', 0.0):.1f}/100, while {target_company} is at {target_row.get('consistency_score', 0.0):.1f}/100. "
            "A steadier rhythm usually makes learning cleaner and helps viewers know when to expect the next video."
        ),
        "slide_06": (
            f"{target_company} currently splits its recent sample across {target_row.get('tofu_pct', 0.0):.1f}% awareness, {target_row.get('mofu_pct', 0.0):.1f}% consideration, and {target_row.get('bofu_pct', 0.0):.1f}% proof-oriented coverage. "
            "If proof-stage coverage stays light, the channel may help discovery without doing enough to support decision-stage confidence."
        ),
        "slide_07": (
            f"{engagement_leader} currently has the strongest recent average engagement at {company_data.get(engagement_leader, {}).get('avg_engagement_rate', 0.0):.3f}%. "
            "The client should care about whether their own engagement level is improving consistently, not just whether one video spikes."
        ),
        "slide_08": (
            f"{top_video_company} owns the strongest single recent top-video result in this sample at {top_video_views:,} views. "
            "Compare views-per-day and engagement rate here to decide whether the winner reflects packaging, relevance, or unusually strong distribution."
        ),
        "slide_09": (
            f"{theme_leader} covers the broadest range of detected themes in the current sample, spanning {len(topic_clusters.get('company_coverage', {}).get(theme_leader, []))} clusters. "
            "This matters because breadth can improve discoverability, but tighter ownership of a few high-intent themes can still outperform a broader mix."
        ),
        "slide_10": (
            f"For {target_company}, the current best-performing length reads as {target_row.get('best_performing_length', 'mixed')}, with short-form engagement at {target_row.get('short', {}).get('avg_engagement_rate', 0.0):.2f}%. "
            "Use this as a planning signal for the next test, not as a rule to abandon longer educational assets entirely."
        ),
        "slide_11": (
            f"{timestamp_zero} of {len(companies)} channels show 0% timestamps in the fetched sample, while {target_company} currently scores {seo_scores.get(target_company, {}).get('seo_score', 0.0):.1f}/100 on discovery setup. "
            "That usually points to avoidable packaging friction rather than a content-quality problem."
        ),
        "slide_12": (
            f"The strongest current whitespace signal is {top_gap_label or 'an underserved theme'}, scoring {top_gap_score:.0f}/100 on the opportunity model. "
            "Use this as a prioritization signal for what to test next rather than proof that the topic will automatically convert."
        ),
        "slide_13": (
            f"The highest-priority moves are built around {target_company}'s current {target_row.get('avg_engagement_rate', 0.0):.3f}% engagement and {target_row.get('consistency_score', 0.0):.1f}/100 consistency. "
            "The goal is to fix the largest leverage points first instead of spreading effort across too many small ideas."
        ),
        "slide_14": (
            f"The medium-priority moves are there to support the bigger plan, not distract from it. "
            f"Use them after the highest-priority tests are underway and compare them against {target_row.get('seo_score', 0.0):.1f}/100 as the current SEO baseline."
        ),
        "slide_15": (
            f"{target_company} currently ranks #{rpi_scores.get(target_company, {}).get('rank', 999)} with a health score of {rpi_scores.get(target_company, {}).get('rpi_score', 0.0):.1f}. "
            "This ending should be read as a realistic growth snapshot, not a win-loss verdict against bigger brands."
        ),
        "slide_16": (
            f"The 90-day plan should respond to the current {target_row.get('mean_gap_days', 0.0):.1f}-day average upload gap and the strongest theme signal available. "
            "What matters most is turning one clear recommendation into a measurable repeatable habit over the next 8 to 12 weeks."
        ),
    }


def validate_slide_interpretations(generated: dict[str, str], fallback: dict[str, str]) -> dict[str, str]:
    expected_keywords = {
        "slide_02": ("rpi", "engagement", "consistency", "peer"),
        "slide_03": ("subscriber", "video", "audience", "channel"),
        "slide_04": ("score", "rank", "benchmark", "health"),
        "slide_05": ("consistency", "cadence", "gap", "publish"),
        "slide_06": ("awareness", "consideration", "proof", "funnel", "buyer"),
        "slide_07": ("engagement", "trend", "rate"),
        "slide_08": ("views", "video", "per day", "engagement"),
        "slide_09": ("theme", "topic", "cluster", "discoverability"),
        "slide_10": ("short", "medium", "long", "length", "format"),
        "slide_11": ("seo", "timestamp", "description", "discover"),
        "slide_12": ("opportunity", "theme", "signal", "score"),
        "slide_13": ("priority", "engagement", "consistency", "move"),
        "slide_14": ("priority", "seo", "baseline", "move"),
        "slide_15": ("rank", "score", "snapshot", "growth"),
        "slide_16": ("day", "week", "month", "plan"),
    }
    final: dict[str, str] = {}
    for slide_key, fallback_text in fallback.items():
        candidate = str(generated.get(slide_key, "") or "").strip()
        lowered = candidate.lower()
        keyword_match = any(keyword in lowered for keyword in expected_keywords.get(slide_key, ()))
        has_number = any(ch.isdigit() for ch in candidate)
        too_vague = not candidate or candidate.endswith(":") or candidate.lower().startswith("interpretation:")
        final[slide_key] = candidate if candidate and has_number and keyword_match and not too_vague else fallback_text
    return final


def no_cache_headers() -> dict[str, str]:
    return {
        "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
        "Pragma": "no-cache",
        "Expires": "0",
    }


@app.get("/health")
async def health():
    return JSONResponse({"status": "ok", "version": "1.0.0"})


@app.get("/generate")
async def generate(
    company: str = Query(...),
    competitors: str = Query(default=""),
):
    return EventSourceResponse(report_pipeline(company, competitors))


async def report_pipeline(company: str, competitors: str):
    raw_company_data: dict = {}
    processed_data: dict = {}

    try:
        # ----------------------------------------------------------------
        # STEP 0 — Parse input
        # ----------------------------------------------------------------
        competitor_list = [c.strip() for c in competitors.split(",") if c.strip()][:4]
        all_companies = [company.strip()] + competitor_list
        total_steps = len(all_companies) * 2 + 7
        current_step = 0

        def progress() -> int:
            return min(int(current_step / total_steps * 100), 99)

        def event(status: str) -> str:
            return json.dumps({"status": status, "progress": progress()})

        # ----------------------------------------------------------------
        # STEP A — Fetch YouTube channel + videos for each company
        # ----------------------------------------------------------------
        for company_name in all_companies:
            yield event(f"Searching for {company_name} on YouTube...")

            try:
                channel = await asyncio.get_event_loop().run_in_executor(
                    None, youtube_service.find_channel, company_name
                )
            except Exception as e:
                logger.warning(f"find_channel error for {company_name}: {e}")
                channel = {}

            # find_channel returns {} if not found — check for channel_id key
            if not channel or not channel.get("channel_id"):
                yield event(f"Could not find official channel for {company_name} — skipping")
                current_step += 2
                continue

            channel_id = channel["channel_id"]
            yield event(
                f"Found {channel['title']} "
                f"({channel.get('subscriber_count', 0):,} subscribers) — fetching videos..."
            )

            try:
                videos = await asyncio.get_event_loop().run_in_executor(
                    None, youtube_service.get_recent_videos, channel_id, 50
                )
            except Exception as e:
                logger.warning(f"get_recent_videos error for {company_name}: {e}")
                videos = []

            if not videos:
                yield event(f"No videos found for {company_name} — skipping")
                current_step += 2
                continue

            # Sample up to 5 video_ids for comment fetching
            sampled_ids = [v["video_id"] for v in videos[:5] if v.get("video_id")]
            all_comments = {}
            for vid_id in sampled_ids:
                try:
                    comments = await asyncio.get_event_loop().run_in_executor(
                        None, youtube_service.get_top_comments, vid_id, 10
                    )
                    all_comments[vid_id] = comments
                except Exception:
                    all_comments[vid_id] = []

            raw_company_data[company_name] = {
                "channel": channel,
                "videos": videos,
                "comments": all_comments,
            }
            current_step += 2

        if not raw_company_data:
            yield json.dumps({
                "status": "error",
                "message": "No valid YouTube channels found for any of the entered companies. Please check the company names and try again.",
                "progress": 0,
            })
            return

        # ----------------------------------------------------------------
        # STEP B — Compute analytics for each company
        # ----------------------------------------------------------------
        yield event("Analysing video performance metrics...")

        for company_name, raw_data in raw_company_data.items():
            videos = raw_data["videos"]
            channel = raw_data["channel"]

            engagement   = analytics_service.compute_engagement_metrics(videos)
            consistency  = analytics_service.compute_upload_consistency(videos)
            funnel       = analytics_service.classify_content_funnel(videos)
            length_strat = analytics_service.analyse_video_length_strategy(videos)
            title_pats   = analytics_service.analyse_title_patterns(videos)
            format_mix   = analytics_service.analyse_format_mix(videos)
            view_vel     = analytics_service.compute_recent_view_velocity(videos)
            seo_full     = seo_service.score_video_seo(videos)

            # Sort videos by view_count descending for top_videos
            top_videos = sorted(
                videos, key=lambda v: v.get("view_count", 0), reverse=True
            )[:5]

            # Build the flat merged dict that pptx_service accesses directly.
            processed_data[company_name] = {
                # Channel fields
                **channel,
                # Engagement fields
                **engagement,
                # Consistency fields
                **consistency,
                # Funnel fields
                **funnel,
                # Length strategy — keep nested (short/medium/long buckets)
                "short": length_strat.get("short", {}),
                "medium": length_strat.get("medium", {}),
                "long": length_strat.get("long", {}),
                "best_performing_length": length_strat.get("best_performing_length", ""),
                # Title pattern fields
                "all_caps_words_ratio": title_pats.get("all_caps_words_ratio", 0),
                "listicle_count": title_pats.get("listicle_count", 0),
                "tutorial_count": title_pats.get("tutorial_count", 0),
                "thought_leadership_count": title_pats.get("thought_leadership_count", 0),
                "product_led_count": title_pats.get("product_led_count", 0),
                # dominant_strategy is a dict — keep as-is for pptx_service
                "dominant_strategy": title_pats.get("dominant_strategy", {}),
                # Flatten dominant_strategy fields for ai_service prompts
                "dominant_strategy_label": title_pats.get("dominant_strategy", {}).get("label", ""),
                "dominant_strategy_description": title_pats.get("dominant_strategy", {}).get("description", ""),
                # Format mix and velocity
                "format_mix": format_mix,
                "dominant_format": format_mix.get("dominant_format", ""),
                "dominant_format_pct": format_mix.get("dominant_format_pct", 0.0),
                "format_diversity_score": format_mix.get("format_diversity_score", 0.0),
                "view_velocity": view_vel,
                # SEO fields (top-level and full dict)
                "seo_score": seo_full.get("seo_score", 0),
                "seo_full": seo_full,
                # Raw data
                "videos": videos,
                "top_videos": top_videos,
                "comments": raw_data.get("comments", {}),
            }

        current_step += 1

        # ----------------------------------------------------------------
        # STEP C — Topic clustering
        # ----------------------------------------------------------------
        yield event("Running content topic clustering...")

        all_videos_by_company = {
            name: data["videos"] for name, data in processed_data.items()
        }
        topic_clusters = analytics_service.cluster_content_topics(all_videos_by_company)
        current_step += 1

        # ----------------------------------------------------------------
        # STEP D — Google Trends
        # ----------------------------------------------------------------
        yield event("Fetching Google Trends data for content gap topics...")

        gap_topics = clean_gap_topics_for_reporting(
            analytics_service,
            topic_clusters.get("gap_topics", []),
        )
        trends_data = {}
        if gap_topics:
            try:
                trends_data = await asyncio.get_event_loop().run_in_executor(
                    None, seo_service.get_topic_trends, gap_topics[:5]
                )
            except Exception as e:
                logger.warning(f"get_topic_trends error: {e}")
                trends_data = {}

        # compute_opportunity_scores needs competitor_coverage from topic_clusters
        opportunity_scores = []
        fallback_opportunity_scores = build_fallback_opportunity_scores(
            target_company=company.strip(),
            target_data=processed_data.get(company.strip(), {}) or next(iter(processed_data.values()), {}),
            processed_data=processed_data,
        )
        try:
            opportunity_scores = seo_service.compute_opportunity_scores(
                gap_topics[:5],
                trends_data,
                topic_clusters.get("cluster_coverage", {}),
            )
        except Exception as e:
            logger.warning(f"compute_opportunity_scores error: {e}")
        opportunity_scores = filter_client_safe_opportunity_scores(
            analytics_service,
            opportunity_scores,
        )
        fallback_opportunity_scores = filter_client_safe_opportunity_scores(
            analytics_service,
            fallback_opportunity_scores,
        )
        if not opportunity_scores:
            opportunity_scores = list(fallback_opportunity_scores)
        elif len(opportunity_scores) < 3:
            seen_topics = {
                str(item.get("topic", "")).strip().lower()
                for item in opportunity_scores
                if item.get("topic")
            }
            for candidate in fallback_opportunity_scores:
                candidate_topic = str(candidate.get("topic", "")).strip().lower()
                if not candidate_topic or candidate_topic in seen_topics:
                    continue
                opportunity_scores.append(candidate)
                seen_topics.add(candidate_topic)
                if len(opportunity_scores) >= 5:
                    break
        if not gap_topics and opportunity_scores:
            gap_topics = [str(item.get("topic", "")).strip() for item in opportunity_scores[:5] if item.get("topic")]

        current_step += 1

        # ----------------------------------------------------------------
        # STEP E — RPI
        # ----------------------------------------------------------------
        yield event("Computing Relative Performance Index scores...")

        rpi_input = {}
        for company_name, data in processed_data.items():
            sub_count = max(data.get("subscriber_count", 1), 1)
            views_per_video = data.get("views_per_video", 0)
            views_per_sub = (views_per_video / sub_count) * 100

            covered_clusters = topic_clusters.get("company_coverage", {}).get(
                company_name, []
            )
            total_clusters = max(len(topic_clusters.get("clusters", [{"id": 1}])), 1)
            topic_diversity = (len(covered_clusters) / total_clusters) * 100

            rpi_input[company_name] = {
                "avg_engagement_rate": data.get("avg_engagement_rate", 0),
                "views_per_subscriber": views_per_sub,
                "consistency_score": data.get("consistency_score", 0),
                "topic_diversity_score": topic_diversity,
                "seo_score": data.get("seo_score", 0),
            }

        rpi_scores = analytics_service.compute_rpi(rpi_input)

        # Write rpi fields back into processed_data so ai_service prompts work
        for company_name in processed_data:
            rpi_payload = rpi_scores.get(company_name, {})
            processed_data[company_name]["rpi_score"] = rpi_payload.get("rpi_score", 0)
            processed_data[company_name]["rank"] = rpi_payload.get("rank", 0)

        current_step += 1

        # ----------------------------------------------------------------
        # STEP F — AI narrative generation
        # ----------------------------------------------------------------
        yield event("Generating executive summary with AI...")

        # Build the input dict for generate_executive_summary
        ai_summary_input = {
            name: {
                "rpi_score":           processed_data[name].get("rpi_score", 0),
                "rank":                processed_data[name].get("rank", 0),
                "avg_engagement_rate": processed_data[name].get("avg_engagement_rate", 0),
                "consistency_score":   processed_data[name].get("consistency_score", 0),
                "funnel_label":        processed_data[name].get("funnel_label", ""),
                "tofu_pct":            processed_data[name].get("tofu_pct", 0),
                "mofu_pct":            processed_data[name].get("mofu_pct", 0),
                "bofu_pct":            processed_data[name].get("bofu_pct", 0),
            }
            for name in processed_data
        }

        executive_summary = await asyncio.get_event_loop().run_in_executor(
            None, ai_service.generate_executive_summary, ai_summary_input
        )
        executive_summary = normalize_executive_summary_text(executive_summary)
        if not executive_summary:
            executive_summary = normalize_executive_summary_text(fallback_executive_summary(
                list(processed_data.keys()),
                rpi_scores,
            ))
        await asyncio.sleep(2)

        yield event("Generating competitor strategy profiles...")

        # Build the input dict for generate_strategy_profiles
        strategy_profiles_input = {
            name: {
                "dominant_strategy_label":       processed_data[name].get("dominant_strategy_label", ""),
                "dominant_strategy_description": processed_data[name].get("dominant_strategy_description", ""),
                "funnel_label":                  processed_data[name].get("funnel_label", ""),
                "tofu_pct":                      processed_data[name].get("tofu_pct", 0),
                "mofu_pct":                      processed_data[name].get("mofu_pct", 0),
                "bofu_pct":                      processed_data[name].get("bofu_pct", 0),
                "best_performing_length":        processed_data[name].get("best_performing_length", ""),
                "consistency_score":             processed_data[name].get("consistency_score", 0),
                "tutorial_count":                processed_data[name].get("tutorial_count", 0),
                "listicle_count":                processed_data[name].get("listicle_count", 0),
                "thought_leadership_count":      processed_data[name].get("thought_leadership_count", 0),
                "product_led_count":             processed_data[name].get("product_led_count", 0),
            }
            for name in processed_data
        }

        strategy_profiles = await asyncio.get_event_loop().run_in_executor(
            None, ai_service.generate_strategy_profiles, strategy_profiles_input
        )
        await asyncio.sleep(2)

        yield event("Analysing content gaps...")
        gap_analysis = await asyncio.get_event_loop().run_in_executor(
            None, ai_service.generate_gap_analysis, gap_topics, trends_data
        )
        gap_analysis = sanitize_structured_ai_text(gap_analysis)
        if (
            not gap_analysis
            or "does not show a single obvious uncovered theme" in gap_analysis.lower()
        ):
            gap_analysis = build_fallback_gap_analysis_from_opportunities(
                company.strip(),
                opportunity_scores,
            )
        await asyncio.sleep(2)

        yield event("Generating strategic recommendations...")

        target_company = next(
            (
                processed_name
                for processed_name in processed_data
                if processed_name.lower() == company.strip().lower()
            ),
            list(processed_data.keys())[0],
        )
        target_data = processed_data.get(target_company, {})

        recommendations = await asyncio.get_event_loop().run_in_executor(
            None, ai_service.generate_recommendations,
            target_company, target_data, gap_topics
        )
        if recommendations_need_fallback(recommendations):
            recommendations = build_fallback_recommendations(
                target_company,
                target_data,
                gap_topics,
                processed_data.get(target_company, {}).get("seo_score", 0.0),
            )
        recommendations = sanitize_recommendations_for_web(recommendations)
        await asyncio.sleep(2)

        yield event("Building 90-day action plan...")
        current_cadence = target_data.get("mean_gap_days", 7.0)
        planning_context = {
            "funnel_label": target_data.get("funnel_label", ""),
            "tofu_pct": target_data.get("tofu_pct", 0),
            "mofu_pct": target_data.get("mofu_pct", 0),
            "bofu_pct": target_data.get("bofu_pct", 0),
            "best_performing_length": target_data.get("best_performing_length", ""),
            "length_confidence": target_data.get("length_confidence", ""),
            "seo_score": target_data.get("seo_score", 0.0),
            "whitespace_topics": [item.get("topic", "") for item in opportunity_scores[:3] if item.get("topic")] or gap_topics[:3],
        }
        action_plan = await asyncio.get_event_loop().run_in_executor(
            None, ai_service.generate_action_plan, recommendations, current_cadence, planning_context
        )
        action_plan = sanitize_structured_ai_text(action_plan)
        if action_plan_needs_fallback(action_plan):
            action_plan = fallback_action_plan(target_company, current_cadence, planning_context)
        await asyncio.sleep(2)

        yield event("Generating slide interpretations...")

        seo_scores_full = {
            name: processed_data[name].get(
                "seo_full",
                {"seo_score": processed_data[name].get("seo_score", 0), "breakdown": {}},
            )
            for name in processed_data
        }

        deck_context = build_slide_interpretation_context(
            list(processed_data.keys()),
            processed_data,
            rpi_scores,
            seo_scores_full,
            topic_clusters,
            opportunity_scores,
            recommendations,
            target_company,
            action_plan,
        )
        fallback_slide_interpretations = build_fallback_slide_interpretations(
            list(processed_data.keys()),
            processed_data,
            rpi_scores,
            seo_scores_full,
            topic_clusters,
            opportunity_scores,
            recommendations,
            target_company,
        )
        generated_slide_interpretations = await asyncio.get_event_loop().run_in_executor(
            None, ai_service.generate_slide_interpretations, deck_context
        )
        slide_interpretations = validate_slide_interpretations(
            generated_slide_interpretations,
            fallback_slide_interpretations,
        )

        current_step += 1

        # ----------------------------------------------------------------
        # STEP G — Build PPTX
        # ----------------------------------------------------------------
        yield event("Building PowerPoint report (16 slides)...")

        report_id = str(uuid.uuid4())
        pptx_path = f"outputs/{report_id}.pptx"

        report_data = {
            "report_id":             report_id,
            "report_date":           datetime.now().strftime("%B %d, %Y"),
            "companies":             list(processed_data.keys()),
            "target_company":        target_company,
            "executive_summary":     executive_summary,
            "company_data":          processed_data,
            "rpi_scores":            rpi_scores,
            "topic_clusters":        topic_clusters,
            "opportunity_scores":    opportunity_scores,
            "gap_analysis":          gap_analysis,
            "strategy_profiles":     strategy_profiles,
            "recommendations":       recommendations,
            "action_plan":           action_plan,
            "seo_scores":            seo_scores_full,
            "slide_interpretations": slide_interpretations,
            "slide_count":           16,
        }

        await asyncio.get_event_loop().run_in_executor(
            None, pptx_service.generate_report, report_data, pptx_path
        )
        current_step += 1

        # ----------------------------------------------------------------
        # STEP H — Save JSON and complete
        # ----------------------------------------------------------------
        yield event("Saving report data...")

        json_path = f"outputs/{report_id}.json"

        import copy
        json_safe = copy.deepcopy(report_data)
        for cname in json_safe.get("company_data", {}):
            vids = json_safe["company_data"][cname].get("videos", [])
            json_safe["company_data"][cname]["videos"] = vids[:5]
            # Remove comments from JSON (large, not needed for preview)
            json_safe["company_data"][cname].pop("comments", None)

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(json_safe, f, default=str, ensure_ascii=False)

        yield json.dumps({
            "status": "complete",
            "progress": 100,
            "report_id": report_id,
        })

    except Exception as e:
        logger.exception("Pipeline error")
        yield json.dumps({
            "status": "error",
            "message": f"Report generation failed: {str(e)}",
            "progress": 0,
        })


@app.get("/report/{report_id}")
async def get_report(report_id: str):
    json_path = f"outputs/{report_id}.json"
    if not os.path.exists(json_path):
        raise HTTPException(status_code=404, detail="Report not found")
    with open(json_path, "r", encoding="utf-8") as f:
        return JSONResponse(content=json.load(f), headers=no_cache_headers())


@app.get("/download/{report_id}")
async def download_report(report_id: str):
    pptx_path = f"outputs/{report_id}.pptx"
    if not os.path.exists(pptx_path):
        raise HTTPException(status_code=404, detail="Report file not found")
    return FileResponse(
        path=pptx_path,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        filename="competitor_intelligence_report.pptx",
        headers=no_cache_headers(),
    )


@app.get("/")
async def serve_frontend():
    with open("frontend/index.html", "r", encoding="utf-8") as f:
        return HTMLResponse(f.read(), headers=no_cache_headers())
