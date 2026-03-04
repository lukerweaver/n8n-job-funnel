# Automated Job Funnel (n8n + LLM)

An automated job search pipeline built with **n8n workflows, a local LLM, and a lightweight scraping service**.

The system continuously ingests job postings, evaluates them against a resume using a structured scoring rubric, and surfaces the best opportunities automatically.

The goal is to reduce the manual overhead of job searching while improving signal quality.

---

# Overview

Job searching often involves scanning dozens or hundreds of postings, manually evaluating each one for fit, and tracking applications across multiple systems.

This project automates that process by:

1. **Collecting job postings automatically**
2. **Evaluating them with a structured LLM scoring rubric**
3. **Filtering for high-probability matches**
4. **Tracking potential applications**
5. **Sending alerts for strong opportunities**

The system is designed as a lightweight **workflow orchestration pipeline** rather than a monolithic application.

---

# Architecture

```
HiringCafe Searches
        │
        ▼
n8n Ingestion Workflow
        │
        ▼
jobscraper service (Playwright)
        │
        ▼
job_postings Data Table
        │
        ▼
n8n Scoring Workflow
        │
        ▼
Local LLM (Ollama)
        │
        ▼
Structured scoring output
        │
        ▼
Filtered high matches
        │
        ├── Google Sheets application tracker
        │
        └── Email alert
```

Key design principle: **orchestrate systems rather than building a single application.**
Local-first development environment used for this implementation.
Services can be deployed independently in production.

---

# Workflows

The repository contains two n8n workflows.

---

## 1. Job Import Workflow

File:

```
exports/workflows/01_ingest_jobs.json
```

Runs multiple times per day to collect new job postings.

### Flow

```
Schedule Trigger
    ↓
Get search URLs from Google Sheets
    ↓
Call jobscraper service
    ↓
Flatten API results
    ↓
Extract key fields
    ↓
Check if job already exists
    ↓
Insert new job into job_postings table
```

### Purpose

- Automatically import new postings
- Normalize job data
- Deduplicate using `job_id`
- Store in the pipeline's working data table

Example stored fields:

- job_id
- company_name
- title
- salary range
- job description
- apply_url

---

## 2. Job Scoring Workflow

File:

```
exports/workflows/02_score_jobs_llm.json
```

Evaluates new job postings using an LLM scoring rubric.

### Flow

```
Schedule Trigger
    ↓
Retrieve new job postings
    ↓
Retrieve prompt template and resume
    ↓
Merge prompt and job data
    ↓
Render structured prompt
    ↓
Send to local LLM (Ollama)
    ↓
Parse structured JSON output
    ↓
Store score and evaluation
    ↓
Filter high scores
    ↓
Append to application tracker
    ↓
Send email notification
```

### Example outputs

Each job receives:

- `score` (0–25)
- strengths
- gaps
- missing_from_jd
- recommendation
- justification

Jobs scoring **≥20** are surfaced as strong opportunities.

---

# Data Model

The system uses n8n Data Tables as lightweight storage.

---

## job_postings

Important fields:

| Field | Purpose |
|------|--------|
| job_id | unique identifier from source |
| company_name | employer |
| title | job title |
| description | full job description |
| score | LLM fit score |
| strengths | resume alignment highlights |
| gaps | missing or weaker areas |
| missing_from_jd | JD requirements not present in resume |
| recommendation | apply guidance |
| prompt_version | scoring prompt used |

Array outputs from the LLM are serialized to strings for storage.

---

## prompt_library

Stores prompts and resume templates used by the pipeline.

Fields:

| Field | Purpose |
|------|--------|
| prompt_key | logical prompt identifier |
| prompt_version | version tracking |
| system_prompt | evaluation rubric |
| user_prompt_template | prompt template |
| base_resume_template | resume used for evaluation |
| is_active | active prompt version |

This design allows prompts to be updated without modifying workflows.

---

# Prompt Design

The LLM evaluation uses a deterministic schema.

The scoring rubric evaluates five dimensions:

| Dimension | Description |
|----------|-------------|
| domain_fit | alignment with product domain |
| execution_ownership_fit | hands-on delivery experience |
| customer_discovery_fit | user research and feedback loops |
| environment_fit | operating context |
| role_readiness | ability to perform role quickly |

Total score range: **0–25**

Recommendations:

| Score | Recommendation |
|------|---------------|
| 20–25 | Strong Apply |
| 16–19 | Selective Apply |
| 12–15 | Stretch Apply |
| ≤11 | Skip |

---

# Dependencies

This project assumes the following services are available.

---

## n8n

Workflow orchestration platform.

Used for:

- scheduling
- automation logic
- LLM integration
- data orchestration

---

## Ollama

Local LLM runtime.

Example model used:

```
qwen2.5:14b-instruct
```

LLM runs locally to avoid API costs.

---

## Job Scraper Service

This project relies on a small Playwright-based scraping service that retrieves job results from HiringCafe.

Repository:

```
https://github.com/lukerweaver/jobscraper
```

The ingestion workflow calls the service at:

```
http://localhost:8000/jobs/hiringcafe
```

The scraper:

- launches a headless browser using Playwright
- loads the HiringCafe search page
- intercepts the `/api/search-jobs` response
- returns the raw JSON payload to the pipeline

This approach avoids needing to reverse engineer or maintain fragile scraping logic inside the workflow itself.

# Runtime Environment

This project was developed using a **local-first setup** to allow fast iteration and avoid external API costs.

Typical development environment:

- **n8n** running locally
- **Ollama** running locally for LLM inference
- **jobscraper service** running locally (Playwright)
- **Google Sheets** for lightweight external tracking

Example local service endpoints used by the workflows:

```
http://localhost:5678        # n8n
http://localhost:11434       # Ollama
http://localhost:8000        # jobscraper
```

Running the services locally allows:

- rapid prompt experimentation
- near-zero operational cost
- easier debugging of workflow logic

The architecture is not tied to local services and could be deployed using:

- n8n Cloud
- containerized services
- hosted LLM APIs
- serverless scraping services

---

# Setup

## 1. Import workflows

Import the workflows into n8n:

```
exports/workflows/01_ingest_jobs.json
exports/workflows/02_score_jobs_llm.json
```

Workflows are inactive by default.

---

## 2. Create Data Tables

Create the following tables in n8n:

```
job_postings
prompt_library
```

Schemas are provided in:

```
exports/data/
```

---

## 3. Seed the prompt library

Insert the mock row from:

```
prompt_library.seed.mock.json
```

This provides:

- scoring prompt
- resume template
- prompt version

---

## 4. Configure nodes

After importing workflows, configure the following nodes.

### Job Import Workflow

**Get Hiring Cafe Searches**

Connect your Google Sheet containing search URLs.

---

### Job Scoring Workflow

**Add to Tracker**

Connect your application tracker sheet.

**Send a message**

Update recipient email.

**Resume Scoring**

Connect Ollama instance.

---

# Design Decisions

This project intentionally prioritizes **speed to value and system orchestration**.

Key tradeoffs:

### Local LLM

Chosen to avoid API cost while iterating on prompts.

---

### Workflow orchestration over custom code

Using n8n allowed rapid development and experimentation.

---

### Structured JSON LLM output

Using strict schema validation prevents malformed responses from corrupting the pipeline.

---

### Prompt versioning

Prompts are stored in a table to allow experimentation without redeploying workflows.

---

# Future Improvements

Potential enhancements:

- LinkedIn job email ingestion
- resume tailoring pipeline
- scoring analytics dashboard
- automated cover letter generation
- job source deduplication
- multi-resume evaluation

---

# Why this project exists

This system was built to explore how workflow orchestration, structured prompting, and lightweight automation can meaningfully improve job search efficiency.

Rather than manually reviewing dozens of postings daily, the pipeline surfaces a smaller set of high-quality opportunities.

---

# License

MIT