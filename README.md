# Video Competitor Intelligence Tool

Client-facing SaaS analytics for turning competitor video benchmarks into growth decisions a marketing leader can actually use.

A live web application that fetches real YouTube channel and video data for any company and its competitors, analyses it using data science and AI, and generates a downloadable 16-slide PowerPoint report.

---

## What it does

- Accepts a company name and up to 4 competitor names
- Fetches live YouTube channel and video data via the YouTube Data API v3
- Runs engagement analytics, confidence-scored cadence analysis, audience-stage classification, topic clustering, strategic whitespace detection, SEO scoring, and a composite health ranking
- Generates AI-written narratives (executive summary, strategy profiles, gap analysis, recommendations, action plan) using Google Gemini 2.5 Flash
- Streams real-time progress to the browser via Server-Sent Events
- Displays a premium web-based report preview with recommendations and a 90-day action plan
- Generates and serves a downloadable 16-slide PowerPoint file built for executive readouts

---

## Project structure

```
.
├── backend/
│   ├── __init__.py
│   ├── config.py                  # Settings + API key exports
│   ├── main.py                    # FastAPI app + SSE pipeline
│   └── services/
│       ├── __init__.py
│       ├── youtube_service.py     # Phase 1 — YouTube Data API
│       ├── analytics_service.py   # Phase 1 — Data science layer
│       ├── seo_service.py         # Phase 2 — SEO + Google Trends
│       ├── ai_service.py          # Phase 2 — Gemini AI narratives
│       └── pptx_service.py        # Phase 3 — 16-slide PPTX builder
├── frontend/
│   └── index.html                 # Single-page web UI
├── outputs/                       # Generated .pptx and .json files (gitignored)
├── .env.example
├── .env                           # Your actual keys (never commit this)
├── requirements.txt
├── railway.toml
├── Dockerfile
└── README.md
```

---

## Setup (local)

### 1. Clone and install

```bash
git clone <your-repo-url>
cd <project-folder>
pip install -r requirements.txt
```

### 2. Get API keys

| Key | Where to get it | Required? |
|---|---|---|
| `YOUTUBE_API_KEY` | [Google Cloud Console](https://console.cloud.google.com) → APIs & Services → YouTube Data API v3 | ✅ Required |
| `GEMINI_API_KEY` | [Google AI Studio](https://aistudio.google.com/app/apikey) | ✅ Required |
| `GROQ_API_KEY` | [Groq Console](https://console.groq.com) | Optional (Gemini fallback) |
| `SERPAPI_API_KEY` | [SerpApi](https://serpapi.com) | Optional (Google Trends fallback) |

### 3. Configure environment

```bash
cp .env.example .env
# Edit .env and fill in your actual keys
```

### 4. Run locally

```bash
uvicorn backend.main:app --host 0.0.0.0 --port 8080 --reload
```

Open `http://localhost:8080` in your browser.

---

## Test companies (recommended)

| Primary company | Competitors |
|---|---|
| HubSpot | Salesforce, Semrush, Mailchimp, monday.com |
| Wistia | Vimeo, Loom, Vidyard |
| Slack | Zoom, Microsoft Teams, Asana |

---

## Deploying on Railway

1. Push your code to a GitHub repository (ensure `.env` is in `.gitignore`)
2. Go to [railway.app](https://railway.app) and create a new project from your GitHub repo
3. Add environment variables in the Railway dashboard (Settings → Variables):
   - `YOUTUBE_API_KEY`
   - `GEMINI_API_KEY`
   - `GROQ_API_KEY` (optional)
   - `SERPAPI_API_KEY` (optional)
4. Railway will auto-detect the `railway.toml`, build from the root `Dockerfile`, and wait for `/health` to return HTTP 200 before switching traffic
5. Your public URL will be shown in the Railway dashboard

Alternatively, deploy with Docker:
```bash
docker build -t video-ci .
docker run -p 8080:8080 --env-file .env video-ci
```

---

## API endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Health check |
| `GET` | `/generate?company=X&competitors=A,B,C` | SSE stream — runs the full pipeline |
| `GET` | `/report/{report_id}` | JSON report data |
| `GET` | `/download/{report_id}` | Download the .pptx file |
| `GET` | `/` | Serves the web UI |

---

## PowerPoint report structure (16 slides)

1. Cover — growth-intelligence framing and scope
2. Executive Summary — concise leadership briefing
3. Channel Overview — audience scale, publishing depth, and client context
4. Video Marketing Health Score — composite benchmark across peers
5. Upload Cadence & Consistency — posting rhythm with confidence scoring
6. Audience Journey Coverage — awareness, consideration, and proof mix
7. Engagement Rate Analysis — trend quality, not just level
8. Top Performing Videos — strongest recent assets with likely success signals
9. Content Topics & Themes — recurring editorial themes and whitespace
10. Strategic Whitespace Opportunities — where to test next
11. Content Format Performance — short, medium, and long-form results
12. Discovery & Search Visibility — packaging and discoverability scorecard
13. Priority Growth Moves — high-priority actions
14. Priority Growth Moves — medium-priority actions
15. Company Growth Scorecard — comparative snapshot with closing narrative
16. 90-Day Action Plan — near-term execution plan

---

## Notes

- The YouTube Data API v3 free tier has a daily quota of 10,000 units. Each run uses approximately 200–500 units depending on the number of companies.
- Google Trends (pytrends) is an unofficial scraper and may be rate-limited. The tool falls back to SerpApi (if configured) or synthetic values.
- AI generation uses Google Gemini 2.5 Flash. The free tier allows 15 requests per minute; the pipeline includes sleep delays to stay within quota.
- Railway injects a `PORT` variable automatically; the Docker image is configured to listen on `${PORT:-8080}` so the same image works both locally and on Railway.
