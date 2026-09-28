# MarketScoutAI

### Autonomous Web Research & Market Intelligence Agent

MarketScoutAI is an Agentic AI system designed to autonomously research the web, gather and verify evidence, analyze market dynamics, and generate evidence-backed market intelligence reports.

> **20-Day Development Sprint**

---

## Project Vision

The goal of MarketScoutAI is to go beyond a simple "search + LLM + summary" application.

A user provides a market research question, and the system should be able to:

1. Understand the research objective.
2. Create a research plan.
3. Decide what information is required.
4. Discover relevant web sources.
5. Collect and extract information.
6. Store evidence and source information.
7. Detect missing or conflicting information.
8. Perform additional research when required.
9. Analyze competitors, trends, and market structure.
10. Generate an evidence-backed market intelligence report.

### Core Agentic Loop

```text
User Query
    ↓
Research Planner
    ↓
Source Discovery
    ↓
Web Data Collection
    ↓
Evidence Extraction
    ↓
Verification
    ↓
Enough Evidence?
   ↙       ↘
 NO        YES
 ↓          ↓
Research   Market
Again      Analysis
             ↓
       Trend / Competitor
          Analysis
             ↓
       Report Generation
             ↓
        Final Dashboard
```

The research loop is the core of the project: the agent should be able to recognize when available evidence is insufficient and initiate additional research rather than immediately producing an answer.

---

# 20-Day Roadmap

## Phase 1 — Foundation

### Day 1 — Project Setup

* [ ] Establish project structure.
* [ ] Set up Git/GitHub workflow.
* [ ] Create Python virtual environment.
* [ ] Configure environment variables.
* [ ] Create `.gitignore`.
* [ ] Set up initial README.
* [ ] Decide initial technology stack.

**Deliverable:** Project runs locally with a clean development structure.

---

### Day 2 — Python, API & LLM Foundation

Learn and implement only the Python required by the project:

* [ ] Python functions
* [ ] Lists and dictionaries
* [ ] JSON handling
* [ ] Exception handling
* [ ] Environment variables
* [ ] API requests
* [ ] Basic async concepts where required

Build:

```text
Python
  ↓
LLM API
  ↓
Structured JSON Response
```

**Deliverable:** MarketScoutAI can accept a research question and receive a structured LLM response.

---

### Day 3 — Tool System

Create the first research tools:

* [ ] `search_web()`
* [ ] `fetch_page()`
* [ ] `extract_content()`

The LLM should be able to determine when a research tool is required.

**Deliverable:** First tool-using agent.

---

# Phase 2 — Web Intelligence

## Day 4 — Web Research

Build:

```text
Query
 ↓
Search
 ↓
URLs
 ↓
Fetch Pages
 ↓
Extract Content
```

Handle:

* [ ] Failed pages
* [ ] Timeouts
* [ ] Duplicate URLs
* [ ] Empty/irrelevant results

**Deliverable:** Agent can autonomously collect web information.

---

## Day 5 — Information Extraction

Convert unstructured web information into structured evidence.

Example:

```json
{
  "entity": "Product X",
  "price": "₹59,999",
  "features": [],
  "source": "https://example.com",
  "published_date": "2026-09-01",
  "confidence": 0.87
}
```

Store:

* [ ] Source
* [ ] URL
* [ ] Timestamp
* [ ] Extracted claim
* [ ] Supporting evidence
* [ ] Confidence

**Deliverable:** Structured evidence collection.

---

## Day 6 — Research Planner

Given a question such as:

> "Analyze the Indian smartphone market under ₹30,000."

The agent should create a research plan such as:

```text
1. Identify major brands
2. Find products under ₹30,000
3. Collect pricing
4. Collect specifications
5. Analyze recent launches
6. Analyze customer sentiment
7. Identify trends
8. Compare competitors
```

**Deliverable:** Autonomous research planning.

---

# Phase 3 — Agentic Core

## Day 7 — Autonomous Research Loop

Connect planning with tool execution:

```text
Plan
 ↓
Execute
 ↓
Observe
 ↓
Evaluate
 ↓
Choose Next Action
 ↓
Execute Again
```

**Deliverable:** Multi-step autonomous research.

---

## Day 8 — Missing Information Detection

The agent should be able to recognize:

> "I do not have enough information to answer this reliably."

Example:

```text
Required:
✓ Price
✓ Processor
✓ RAM
✗ Battery information

        ↓

Create Follow-up Research Task
        ↓
Search Again
```

**Deliverable:** Research-gap detection.

---

## Day 9 — Research Budget & Stopping Logic

Prevent endless autonomous research.

Implement:

* [ ] Maximum number of sources
* [ ] Maximum research iterations
* [ ] Maximum research time
* [ ] Stopping criteria
* [ ] Research status tracking

Example:

```text
Maximum Sources: 20
Maximum Iterations: 5
```

The agent should determine when sufficient evidence has been collected.

**Major milestone:** By the end of Day 9, the core Agentic AI loop should work.

---

# Phase 4 — Trust & Market Intelligence

## Day 10 — Source Verification

Implement source-aware evidence handling.

Potential source categories:

* Official sources
* Major publications
* Industry sources
* Review sites
* Unknown/low-confidence sources

Every important claim should retain its source.

**Deliverable:** Evidence-backed research.

---

## Day 11 — Conflict Detection

Example:

```text
Source A → ₹29,999
Source B → ₹31,999
```

The agent should detect the conflict and investigate:

* Publication date
* Product variant
* Region
* Source credibility
* Context

**Deliverable:** Fact/conflict verification.

---

## Day 12 — Market Analysis

Turn collected evidence into market intelligence.

### Competitor Analysis

* [ ] Companies
* [ ] Products
* [ ] Pricing
* [ ] Features
* [ ] Positioning

### Market Segmentation

* [ ] Budget
* [ ] Mid-range
* [ ] Premium
* [ ] Other relevant segments

### Trend Detection

* [ ] Feature adoption
* [ ] Pricing movement
* [ ] Product launches
* [ ] Emerging competitors
* [ ] Market shifts

**Deliverable:** Actual market intelligence rather than simple summarization.

---

# Phase 5 — Product & Interface

## Day 13 — Report Generation

Generate a structured market intelligence report:

```text
1. Executive Summary
2. Research Methodology
3. Market Overview
4. Major Players
5. Competitive Analysis
6. Product / Price Analysis
7. Emerging Trends
8. Market Gaps
9. Evidence & Confidence
10. Sources
```

**Deliverable:** Automated evidence-backed market report.

---

## Day 14 — Backend

Build the FastAPI backend and persistence layer.

Planned endpoints:

```text
POST /research
GET  /research/{id}
GET  /research/{id}/status
GET  /research/{id}/sources
GET  /research/{id}/report
```

**Deliverable:** Production-style backend foundation.

---

## Day 15 — Frontend Foundation

Build the Next.js interface.

Main flow:

```text
Home
 ↓
Research Query
 ↓
Research Progress
 ↓
Results Dashboard
 ↓
Full Report
```

**Deliverable:** Usable web application.

---

# Phase 6 — Polish & Evaluation

## Day 16 — Research Visualization

Add useful visualizations:

* [ ] Competitor comparison
* [ ] Price distribution
* [ ] Market segments
* [ ] Trend indicators
* [ ] Source confidence

Keep the interface focused and readable.

**Deliverable:** Professional intelligence dashboard.

---

## Day 17 — Error Handling & Testing

Test failure scenarios:

* [ ] Website unavailable
* [ ] Search API failure
* [ ] No search results
* [ ] Conflicting information
* [ ] LLM failure
* [ ] Malformed LLM response
* [ ] Rate limits
* [ ] Insufficient evidence

**Deliverable:** Reliable application.

---

## Day 18 — Agent Evaluation

Create evaluation cases containing:

* [ ] Research question
* [ ] Expected information
* [ ] Required evidence
* [ ] Hallucination checks
* [ ] Citation checks
* [ ] Research efficiency

Potential metrics:

* Citation coverage
* Factual consistency
* Task completion
* Research iterations
* Unnecessary tool calls

**Deliverable:** Evidence that the agent performs reliably.

---

# Phase 7 — Deployment & Finalization

## Day 19 — Deployment & Documentation

Complete:

* [ ] Frontend deployment
* [ ] Backend deployment
* [ ] Database deployment
* [ ] README
* [ ] Architecture diagram
* [ ] Setup instructions
* [ ] API documentation
* [ ] Screenshots
* [ ] Demo examples
* [ ] Limitations
* [ ] Future improvements

**Deliverable:** Publicly accessible and documented project.

---

## Day 20 — Final Polish & Presentation

No major new features on Day 20.

Final checks:

* [ ] Complete end-to-end user journey
* [ ] Test 2–3 market research queries
* [ ] Verify citations
* [ ] Verify research loop
* [ ] Verify report generation
* [ ] Clean GitHub repository
* [ ] Final README update
* [ ] Prepare project explanation
* [ ] Prepare architecture explanation
* [ ] Prepare agent decision-making explanation
* [ ] Prepare technology-stack explanation
* [ ] Prepare limitations
* [ ] Prepare viva/interview questions

**Final Deliverable:** Deployed, documented, tested, presentation-ready MarketScoutAI.

---

# Milestone Map

```text
DAY 1
Project Starts
      ↓
DAY 3
LLM + Tools Working
      ↓
DAY 6
Research Planner Working
      ↓
DAY 9
AUTONOMOUS RESEARCH LOOP
      ↓
DAY 12
Verification + Market Analysis
      ↓
DAY 15
Backend + Basic UI
      ↓
DAY 18
COMPLETE WORKING PRODUCT
      ↓
DAY 20
DEPLOYED + DOCUMENTED + PRESENTATION READY
```

---

# Must-Have Features

These features are part of the core 20-day scope:

* [ ] LLM integration
* [ ] Web research
* [ ] Tool calling
* [ ] Research planning
* [ ] Autonomous research loop
* [ ] Evidence extraction
* [ ] Source citations
* [ ] Missing-information detection
* [ ] Basic verification
* [ ] Market analysis
* [ ] Report generation
* [ ] Backend
* [ ] Frontend
* [ ] Database/persistence
* [ ] Evaluation
* [ ] README/documentation
* [ ] Deployment

---

# Optional Features

These will only be added if the core system is stable ahead of schedule:

* [ ] Vector database / advanced RAG
* [ ] Advanced sentiment analysis
* [ ] PDF export
* [ ] Scheduled market monitoring
* [ ] Email reports
* [ ] User accounts
* [ ] Multiple LLM providers
* [ ] Advanced visualizations

Optional features must never delay the core project.

---

# Scope Protection

To finish within 20 days, MarketScoutAI will **not** prioritize:

* Building a custom search engine
* Training an LLM from scratch
* Scraping every website on the internet
* Overcomplicated multi-agent architecture without a clear purpose
* Unnecessary UI animations
* Features that do not improve research quality or agent autonomy

The priority is a **working, reliable, explainable Agentic AI system**.

---

# Project Success Criteria

MarketScoutAI will be considered complete when a user can:

```text
Enter a market question
        ↓
Receive an autonomous research plan
        ↓
Watch the agent research sources
        ↓
See evidence being collected
        ↓
See additional research when information is missing
        ↓
See conflicts being handled
        ↓
Receive market analysis
        ↓
Receive an evidence-backed final report
```

The system should be explainable at every major stage.

---

# Development Log

This section will be updated throughout the 20-day development sprint.

| Day    | Focus                            | Status  |
| ------ | -------------------------------- | ------- |
| Day 1  | Project setup                    | Planned |
| Day 2  | Python, API & LLM foundation     | Planned |
| Day 3  | Tool system                      | Planned |
| Day 4  | Web research                     | Planned |
| Day 5  | Information extraction           | Planned |
| Day 6  | Research planner                 | Planned |
| Day 7  | Autonomous research loop         | Planned |
| Day 8  | Missing-information detection    | Planned |
| Day 9  | Research budget & stopping logic | Planned |
| Day 10 | Source verification              | Planned |
| Day 11 | Conflict detection               | Planned |
| Day 12 | Market analysis                  | Planned |
| Day 13 | Report generation                | Planned |
| Day 14 | Backend                          | Planned |
| Day 15 | Frontend foundation              | Planned |
| Day 16 | Research visualization           | Planned |
| Day 17 | Testing & error handling         | Planned |
| Day 18 | Agent evaluation                 | Planned |
| Day 19 | Deployment & documentation       | Planned |
| Day 20 | Final polish & presentation      | Planned |

---

# Development Philosophy

MarketScoutAI will be developed incrementally.

Each milestone should leave the project in a runnable state.

The project will prioritize:

1. **Agentic behavior over unnecessary features**
2. **Evidence over unsupported claims**
3. **Reliability over flashy demos**
4. **Explainability over black-box behavior**
5. **Working software over excessive architecture**
6. **Learning concepts while implementing them**

---

# Future Scope

Possible future directions include:

* Continuous market monitoring
* Scheduled intelligence reports
* Competitive alerts
* Personalized research objectives
* More advanced source credibility scoring
* Long-term research memory
* Multi-market comparison
* Additional data sources
* Advanced agent evaluation
* Human-in-the-loop research approval

---

# Status

**Current Phase:** Planning
**Timeline:** 20 days
**Current Milestone:** Day 1 — Project Setup

---

## Repository

GitHub: https://github.com/anshikamishra28/MarketScoutAI
