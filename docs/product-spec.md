AgentRadar
AI Agent Intelligence That Turns Information Into Decisions
There is too much AI news. You don't need more information. You need to know what actually matters.

1. Project Summary
AgentRadar is an autonomous AI research-intelligence agent focused initially on the rapidly changing AI agents ecosystem.
Instead of simply searching the web and summarizing articles, AgentRadar:
    1    Discovers recent developments across multiple sources.
    2    Delegates research to specialized subagents.
    3    Cross-verifies claims against primary and independent sources.
    4    Separates meaningful signals from hype.
    5    Determines why a development matters.
    6    Personalizes its impact to a user's technology stack.
    7    Converts the research into a concise, visual, memorable briefing.
    8    Recommends a concrete next action.
    9    Can execute an approved follow-up action such as creating a GitHub experiment or research task.
The goal is not to build another AI news reader.
The goal is to build:
An autonomous technology-intelligence analyst for engineering teams.

2. Problem Statement
AI engineering is moving faster than most teams can realistically follow.
Important information is fragmented across:
    •    Research papers
    •    GitHub repositories
    •    Release notes
    •    Official documentation
    •    Company engineering blogs
    •    Product announcements
    •    Benchmarks
    •    Technical articles
    •    Hacker News
    •    Reddit
    •    Community discussions
    •    Framework documentation
An engineering leader considering a decision such as:
"Should we adopt MCP?"
or:
"Should we migrate from LangGraph to OpenAI Agents SDK?"
may need to manually inspect dozens of sources before forming a confident opinion.
The problem is therefore not access to information.
The problem is:
Turning an overwhelming stream of constantly changing information into reliable decisions.
Current solutions often stop at:
Search
   ↓
Summarize
   ↓
Long AI response
AgentRadar instead does:
Discover
   ↓
Research
   ↓
Verify
   ↓
Compare
   ↓
Reason
   ↓
Rank importance
   ↓
Explain
   ↓
Recommend
   ↓
Act with approval

3. Product Thesis
AgentRadar should answer four questions every time:
1. What changed?
What important developments happened?
2. Does it actually matter?
Is this a genuine technical signal or mostly hype?
3. Why does it matter to me?
How does this affect my stack, architecture, product, or engineering decisions?
4. What should I do?
Ignore it?
Monitor it?
Read something?
Run an experiment?
Change architecture?
Create a GitHub issue?

4. Target Users
Initial users:
    •    AI engineers
    •    Staff/principal engineers
    •    Engineering managers
    •    CTOs
    •    Technical founders
    •    AI researchers
    •    Developer-relations teams
    •    AI infrastructure teams
Initial domain:
AI Agents
Future domains could include:
    •    LLM infrastructure
    •    RAG
    •    AI security
    •    Inference
    •    Voice AI
    •    Computer-use agents
    •    Model releases
    •    Vector databases
    •    AI developer tooling
For the hackathon, do not expand beyond AI agents.
A narrow, polished product is better than a broad unfinished platform.

5. Core User Experience
A user opens AgentRadar and sees:
Good morning.

Since your last visit:

64 sources scanned
 9 developments detected
 3 meaningful signals
 1 could affect your architecture

                 [View Today's Radar]
The important number is not:
64 articles found.
It is:
1 thing you should care about.

6. Product Principles
AgentRadar should follow these principles.
Evidence before opinion
Important claims should be supported by reliable sources.
Primary sources first
Official documentation, repositories, papers, benchmarks, and release notes should outweigh secondary commentary.
Signal over volume
Finding 100 articles is less valuable than identifying 3 developments that matter.
Decisions over summaries
Every major briefing should end with:
What should I do?
Memory-first communication
Information should be presented so users can remember the important conclusion later.
Human-controlled actions
Research can run autonomously.
External or potentially consequential actions require explicit approval.
Visible agent activity
Users should understand:
    •    what AgentRadar is doing,
    •    which agents are working,
    •    which tools are being used,
    •    what evidence has been collected,
    •    what it is waiting for,
    •    and why it reached its conclusion.

7. Final High-Level Architecture
flowchart TB

    U["👤 User"]

    UI["🖥️ AgentRadar UI
    Today's Radar
    Deep Research
    Decision Brief
    Knowledge Map"]

    API["⚡ Application API"]

    TF["🧠 TrueForge
    Main Research Orchestrator"]

    U --> UI
    UI --> API
    API --> TF

    TF --> PLAN["Research Planner"]

    PLAN --> NEWS["📰 News Scout"]
    PLAN --> PAPER["📚 Research Paper Scout"]
    PLAN --> GH["💻 GitHub Scout"]
    PLAN --> DOC["📖 Documentation Scout"]
    PLAN --> COMM["💬 Community Scout"]

    NEWS --> WEB["🌐 Live Web / Bright Data"]
    PAPER --> ARXIV["Research / Paper Sources"]
    GH --> GITHUB["GitHub MCP / API"]
    DOC --> WEB
    COMM --> WEB

    NEWS --> EVIDENCE
    PAPER --> EVIDENCE
    GH --> EVIDENCE
    DOC --> EVIDENCE
    COMM --> EVIDENCE

    EVIDENCE["🔎 Evidence & Verification Agent"]

    EVIDENCE --> SIGNAL["📡 Signal Scoring Agent"]

    SIGNAL --> SANDBOX["🔒 TrueForge Sandbox
    comparison
    ranking
    calculations
    generated analysis code"]

    SANDBOX --> SYNTH["🧠 Synthesis / Decision Agent"]

    PROFILE["👤 User Tech Profile
    stack
    interests
    tracked topics"]

    PROFILE --> SYNTH

    SYNTH --> MEMORY["🧩 Memory Formatter"]

    MEMORY --> RESULT["📊 Decision Brief"]

    RESULT --> UI

    SYNTH --> ACTION["⚙️ Action Planner"]

    ACTION --> APPROVAL{"👤 Human Approval"}

    APPROVAL -->|"Reject"| UI

    APPROVAL -->|"Approve"| TOOLS["🔧 Action Tools / MCP"]

    TOOLS --> ISSUE["Create GitHub Issue"]
    TOOLS --> EXP["Create Experiment"]
    TOOLS --> SLACK["Send Team Brief"]
    TOOLS --> TASK["Create Research Task"]

    TF --> SESSION[("💾 Persistent Research Session")]
    SESSION --> TF

8. Simplified Mental Model
The architecture can be remembered as:
               DISCOVER

                  ↓

               VERIFY

                  ↓

                SCORE

                  ↓

               DECIDE

                  ↓

              REMEMBER

                  ↓

                 ACT
This should become one of the core product visuals.

9. Main Agent
Research Orchestrator
The main TrueForge agent should not perform every research task itself.
Its responsibility is to:
    1    Understand the user's question.
    2    Decide what research is required.
    3    Break the problem into research tasks.
    4    Delegate tasks to specialized subagents.
    5    Monitor their progress.
    6    Combine evidence.
    7    Resolve conflicting findings.
    8    Generate a final recommendation.
    9    Decide whether a follow-up action is appropriate.
    10    Request human approval before executing consequential actions.
Example:
User:
"Should our startup adopt MCP for new agent integrations?"

                ↓

Research Orchestrator

                ↓

Creates tasks:

1. Research MCP's current specification.
2. Find recent adoption signals.
3. Analyze ecosystem support.
4. Investigate security concerns.
5. Find production case studies.
6. Compare against direct API integrations.

10. Specialized Subagents
10.1 News Scout
Purpose:
Discover recent developments.
Sources may include:
    •    company announcements,
    •    AI news publications,
    •    technical blogs,
    •    product launches,
    •    release announcements.
Output:
{
  "development": "...",
  "published_at": "...",
  "source": "...",
  "source_type": "news",
  "summary": "...",
  "potential_importance": 8
}

10.2 Research Paper Scout
Purpose:
Find technical evidence.
Looks for:
    •    papers,
    •    benchmarks,
    •    evaluations,
    •    methodology,
    •    empirical results.
Questions:
Is there independent evidence?

What methodology was used?

What does the benchmark actually prove?

What does it NOT prove?

10.3 GitHub Scout
Purpose:
Understand what is happening in the actual developer ecosystem.
Investigates:
    •    repository activity,
    •    releases,
    •    issues,
    •    pull requests,
    •    documentation,
    •    examples,
    •    development activity.
Important because marketing claims and production reality can differ.

10.4 Documentation Scout
Purpose:
Verify product capabilities through primary documentation.
Prioritize:
Official documentation
        >
Official engineering blog
        >
Third-party article
        >
Social media claim

10.5 Community Scout
Purpose:
Understand developer experience and emerging concerns.
Potential sources:
    •    Hacker News
    •    Reddit
    •    technical forums
    •    public engineering discussions
Community evidence should be treated differently from official documentation.
For example:
Official docs:
HIGH factual confidence

Benchmark:
HIGH/MEDIUM depending on methodology

GitHub discussion:
MEDIUM

Reddit anecdote:
LOW/MEDIUM

Marketing tweet:
LOW

11. Evidence Verification Agent
This is one of AgentRadar's most important components.
It receives claims from all research agents.
Example claim:
"Framework X is 40% faster than Framework Y."
The Verification Agent asks:
Who made this claim?

Is there an original source?

Was it independently verified?

What benchmark produced the result?

Are the testing conditions comparable?

Is the result still current?

Are multiple sources repeating the same original claim?
Output:
{
  "claim": "...",
  "confidence": 0.91,
  "primary_sources": [],
  "supporting_sources": [],
  "contradicting_sources": [],
  "evidence_quality": "HIGH"
}

12. Signal vs Hype Engine
This should be one of AgentRadar's signature features.
Every major development receives a:
Signal Score
Example:
9.1 / 10

🔴 MAJOR SIGNAL
or:
2.3 / 10

⚪ MOSTLY NOISE
Possible factors:
Technical significance       25%
Independent validation       20%
Ecosystem adoption           15%
Developer impact             15%
Production readiness         10%
Novelty                      10%
User-stack relevance          5%
Hackathon MVP can use a simpler weighted scoring algorithm.

13. Signal Categories
Use four memorable categories:
🔴 MAJOR SHIFT
Architecture or strategy may need to change.

🟠 WATCH
Potentially important, but evidence/adoption is immature.

🟢 USEFUL NOW
Something teams can practically use today.

⚪ NOISE
Interesting headline without enough evidence or impact.
This becomes a major part of the UI.

14. Personalization Layer
This differentiates AgentRadar from generic AI newsletters.
A user can define:
stack:
  backend:
    - Python
    - FastAPI

  agents:
    - LangGraph
    - OpenAI

  database:
    - PostgreSQL
    - pgvector

  cloud:
    - AWS

interests:
  - agents
  - MCP
  - RAG
  - observability
Then AgentRadar calculates:
GLOBAL IMPORTANCE

        versus

IMPORTANCE TO YOU
Example:
New Java Agent Framework

Global signal:
7.8

Impact on your stack:
2.1

Recommendation:
IGNORE FOR NOW
Compared with:
Breaking LangGraph persistence change

Global signal:
6.9

Impact on your stack:
9.4

Recommendation:
INVESTIGATE THIS WEEK
That is substantially more valuable.

15. Memory-First Presentation Layer
The product should deliberately prevent long walls of text.
Every important briefing should answer:
WHAT HAPPENED?

WHY DOES IT MATTER?

WHAT SHOULD I REMEMBER?

WHAT SHOULD I DO?
Example:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

MCP ADOPTION ACCELERATES

SIGNAL
🔴 9.1 / 10

WHY IT MATTERS
Major AI providers are converging around
standardized tool connectivity.

FOR YOUR STACK
HIGH IMPACT

REMEMBER
"MCP standardizes how agents reach tools."

RECOMMENDATION
Use MCP for new integrations.
Do not rewrite existing stable integrations yet.

CONFIDENCE
█████████░ 91%

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

16. Today's Radar
Home-screen concept:
┌─────────────────────────────────────────────┐
│ AGENTRADAR                         AUG 29   │
├─────────────────────────────────────────────┤
│                                             │
│  TODAY IN AI AGENTS                         │
│                                             │
│  62 sources scanned                         │
│   8 developments                            │
│   3 signals                                 │
│   1 affects your architecture               │
│                                             │
├─────────────────────────────────────────────┤
│                                             │
│ 🔴 9.2                                      │
│ Major agent framework release               │
│                                             │
│ Why it matters → _________                  │
│ Impact on you → HIGH                        │
│                                             │
│ [View Intelligence]                         │
│                                             │
├─────────────────────────────────────────────┤
│                                             │
│ 🟠 7.4                                      │
│ New agent benchmark published               │
│                                             │
│ [View Intelligence]                         │
│                                             │
├─────────────────────────────────────────────┤
│                                             │
│ ⚪ 2.1                                      │
│ Viral "Agents Are Dead" discussion          │
│                                             │
│ Verdict → Mostly hype                       │
│                                             │
└─────────────────────────────────────────────┘

17. Deep Research Mode
Users can ask:
"Should we migrate from LangGraph to OpenAI Agents SDK?"
Then show the work happening.
RESEARCH MISSION

Question
Should we migrate from LangGraph to OpenAI Agents SDK?

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

✓ Planning research

● Documentation Scout
  Comparing capabilities...

● GitHub Scout
  Inspecting releases and activity...

● Research Scout
  Finding benchmarks...

✓ News Scout
  12 relevant developments found

● Verification Agent
  Cross-checking claims...

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Evidence collected: 27 sources
Conflicts detected: 3
Verified claims: 14
The visible workflow is very important.
Do not hide agent execution behind a spinner.

18. Decision Brief
Final result:
┌───────────────────────────────────────────┐
│ DECISION BRIEF                            │
│                                           │
│ LangGraph → OpenAI Agents SDK?            │
├───────────────────────────────────────────┤
│                                           │
│ VERDICT                                   │
│                                           │
│ STAY ON LANGGRAPH FOR NOW                 │
│                                           │
│ Confidence █████████░ 89%                 │
│                                           │
├───────────────────────────────────────────┤
│ WHY                                       │
│                                           │
│ 1. Migration benefit currently small      │
│ 2. Current system already uses LangGraph  │
│ 3. LangGraph gives greater graph control  │
│                                           │
├───────────────────────────────────────────┤
│ REMEMBER                                  │
│                                           │
│ LangGraph = Control                       │
│ Agents SDK = Simplicity                   │
│                                           │
├───────────────────────────────────────────┤
│ RECOMMENDED NEXT STEP                     │
│                                           │
│ Run a small Agents SDK experiment.        │
│                                           │
│ [Create Experiment]                       │
└───────────────────────────────────────────┘

19. Action Layer
Research should not be the end of the workflow.
The agent can recommend:
Create GitHub experiment

Create GitHub issue

Draft engineering brief

Send Slack summary

Create comparison benchmark

Schedule follow-up research
For the hackathon, implement ONE strong action.
Recommended:
Create GitHub Experiment
Example:
AgentRadar recommends validating the
OpenAI Agents SDK before considering migration.

I can create:

experiments/
└── openai-agents-sdk/
    ├── README.md
    ├── benchmark.py
    ├── agent.py
    └── requirements.txt

and open a GitHub issue documenting
the hypothesis and success criteria.

Estimated actions:

• Create 4 files
• Create branch
• Open pull request
• Open GitHub issue

Proceed?

        [Cancel]      [Approve]
Only after approval should the action execute.

20. Human Approval Architecture
flowchart LR

    R["Research Complete"]

    A["Agent recommends action"]

    P["Action Plan Generated"]

    H{"Human Approval"}

    X["Cancelled"]

    T["Tool / MCP Execution"]

    RESULT["Action Complete"]

    R --> A
    A --> P
    P --> H

    H -->|"Reject"| X
    H -->|"Approve"| T

    T --> RESULT
This creates a clean safety story:
AgentRadar can research autonomously, but humans control consequential actions.

21. Sandboxed Execution
The TrueForge sandbox should perform real useful work.
Good uses:
Signal calculation
collect scores
     ↓
normalize evidence
     ↓
calculate signal score
Benchmark comparison
Agent can generate Python code to compare benchmark results.
Data processing
27 sources
     ↓
deduplicate
     ↓
extract dates
     ↓
calculate source diversity
     ↓
rank evidence
Experiment generation
Generated experiment or analysis code should execute safely in the sandbox before being proposed to the user.
The sandbox should be visible in the demo.
Example UI:
✓ Running analysis in isolated sandbox

Executed:
signal_analysis.py

Result:

Framework A score: 8.4
Framework B score: 7.1

No external systems modified.

22. Persistent Sessions
Research missions may take multiple steps.
Persist:
research_session_id

question

research_plan

subagent_tasks

sources

claims

verification_results

signal_scores

final_decision

pending_actions

approval_status
If the user refreshes the browser:
Research Mission #AR-2041

Status:
COMPLETE

27 sources analyzed
14 claims verified
3 disagreements resolved
1 recommendation generated
The research should not disappear.

23. Suggested Data Model
research_sessions
id
user_id
question
status
created_at
completed_at
final_verdict
confidence
sources
id
session_id
url
title
source_type
publisher
published_at
retrieved_at
reliability_score
claims
id
session_id
claim
confidence
verification_status
claim_sources
claim_id
source_id
relationship

SUPPORTS
CONTRADICTS
PRIMARY
developments
id
title
summary
signal_score
category
published_at
actions
id
session_id
action_type
action_payload
approval_status
execution_status

24. Suggested Technology Architecture
For hackathon speed:
Frontend
    ↓
Next.js / React

Backend API
    ↓
FastAPI or lightweight Node API

Agent Runtime
    ↓
TrueForge

Models
    ↓
OpenAI / supported provider

Research
    ↓
TrueForge Web Tools
Bright Data
Public APIs

Developer Evidence
    ↓
GitHub MCP/API

Safe Computation
    ↓
TrueForge Sandbox

Persistence
    ↓
SQLite initially
or PostgreSQL

External Action
    ↓
GitHub MCP/API

Code Review
    ↓
GitHub PR
    ↓
Qodo
Do not over-engineer infrastructure.

25. Full Technical Architecture
flowchart TB

    subgraph CLIENT["Frontend"]
        DASH["Today's Radar"]
        DEEP["Deep Research"]
        BRIEF["Decision Brief"]
        MAP["Knowledge Map"]
        LIVE["Agent Activity Timeline"]
    end

    subgraph APP["Application Layer"]
        API["Backend API"]
        AUTH["User / Profile"]
        STORE["Application Database"]
    end

    subgraph HARNESS["TrueForge Agent Runtime"]
        ORCH["Research Orchestrator"]

        subgraph AGENTS["Research Subagents"]
            N["News Scout"]
            P["Paper Scout"]
            G["GitHub Scout"]
            D["Docs Scout"]
            C["Community Scout"]
        end

        V["Evidence Verification"]
        S["Signal Scoring"]
        Y["Decision Synthesis"]
        A["Action Planner"]

        SB["Sandbox Execution"]
        SESSION["Persistent Session"]
        APPROVAL["Human Approval"]
    end

    subgraph DATA["External Intelligence"]
        BD["Bright Data / Live Web"]
        PAPERS["Research Sources"]
        GITHUB["GitHub"]
        DOCS["Official Documentation"]
        COMMUNITY["Public Discussions"]
    end

    subgraph ACTIONS["Action Targets"]
        GHI["GitHub Issue"]
        EXP["Experiment PR"]
        MSG["Team Brief"]
    end

    CLIENT --> API

    API --> AUTH
    API --> STORE
    API --> ORCH

    ORCH --> N
    ORCH --> P
    ORCH --> G
    ORCH --> D
    ORCH --> C

    N --> BD
    P --> PAPERS
    G --> GITHUB
    D --> DOCS
    C --> BD
    C --> COMMUNITY

    N --> V
    P --> V
    G --> V
    D --> V
    C --> V

    V --> S

    S --> SB
    SB --> Y

    AUTH --> Y

    Y --> A

    Y --> STORE

    A --> APPROVAL

    APPROVAL --> GHI
    APPROVAL --> EXP
    APPROVAL --> MSG

    ORCH <--> SESSION

    ORCH --> LIVE
    Y --> BRIEF

26. Research Workflow
sequenceDiagram

    actor User

    participant UI
    participant TrueForge
    participant Planner
    participant Agents
    participant Web
    participant Verify
    participant Sandbox
    participant Decision
    participant Approval
    participant GitHub

    User->>UI: Ask research question

    UI->>TrueForge: Start research mission

    TrueForge->>Planner: Create research plan

    Planner->>Agents: Delegate tasks

    par Parallel research
        Agents->>Web: Search latest sources
        Agents->>GitHub: Inspect repositories
        Agents->>Web: Find papers/docs
    end

    Agents->>Verify: Submit evidence

    Verify->>Verify: Cross-check claims

    Verify->>Sandbox: Analyze evidence

    Sandbox-->>Decision: Structured results

    Decision->>Decision: Generate recommendation

    Decision-->>UI: Decision Brief

    User->>UI: Create experiment

    UI->>TrueForge: Request action

    TrueForge->>Approval: Pause

    Approval-->>User: Approve?

    User->>Approval: Approve

    Approval->>GitHub: Create experiment / issue

    GitHub-->>UI: Action completed

27. Source Reliability Model
AgentRadar should distinguish sources.
Suggested hierarchy:
Tier A

Official documentation
Peer-reviewed / original paper
Official repository
Original benchmark

          ↓

Tier B

Reputable engineering publication
Company engineering blog
Independent technical analysis

          ↓

Tier C

GitHub discussion
Hacker News
Technical community discussion

          ↓

Tier D

Social media
Unverified claims
Marketing posts
A viral claim supported only by Tier D sources should not receive a high-confidence recommendation.

28. Conflict Detection
AgentRadar becomes more trustworthy when it explicitly shows disagreement.
Example:
⚠ Evidence Conflict Detected

OpenAI benchmark:
+34% improvement

Independent benchmark:
+8% improvement

AgentRadar assessment:

The performance improvement appears real,
but the vendor benchmark likely overstates
the magnitude.

Confidence: 78%
This is much better than pretending all sources agree.

29. Knowledge Map — Stretch Feature
After the MVP works, research can create a visual map:
                         AI AGENTS
                             │
          ┌──────────────────┼───────────────────┐
          │                  │                   │
    ORCHESTRATION          TOOLS              MEMORY
          │                  │                   │
    ┌─────┴─────┐       ┌────┴─────┐      ┌─────┴─────┐
 LangGraph   CrewAI     MCP       APIs    Vector DB  State
     │
     ├── Graph execution
     ├── Persistence
     └── Human-in-loop
Each node can contain:
What it is

Why it matters

Latest developments

Important papers

Major tools

What changed recently
Do NOT build this before the core workflow works.

30. What Makes AgentRadar Different
AgentRadar is not:
❌ Google Search
Search finds links.
AgentRadar forms an evidence-backed decision.
❌ Perplexity
Question → research answer.
AgentRadar continuously identifies signals, personalizes impact, and can execute follow-up actions.
❌ AI Newsletter
Newsletter decides what's generally interesting.
AgentRadar decides what matters to your stack.
❌ RSS Reader
RSS organizes content.
AgentRadar evaluates evidence.
❌ Generic research agent
Generic:
Question
↓
Search
↓
Summary
AgentRadar:
Question
↓
Research Plan
↓
Parallel Specialists
↓
Evidence Verification
↓
Conflict Detection
↓
Signal Scoring
↓
Stack Impact
↓
Decision
↓
Memorable Explanation
↓
Recommended Action
↓
Human Approval
↓
Execution

31. Hackathon MVP
MUST HAVE
1. Deep Research Question
Example:
Should our engineering team adopt MCP for new AI-agent integrations?
2. TrueForge Orchestrator
Controls research lifecycle.
3. At least 3 Subagents
Recommended:
Documentation Agent
GitHub Agent
News/Research Agent
4. Real Web Research
Retrieve current information rather than using model knowledge alone.
5. Evidence Verification
Show which claims are strongly versus weakly supported.
6. Signal Score
Generate:
Major Shift
Watch
Useful Now
Noise
7. Decision Brief
Beautiful final output.
8. Sandbox
Run actual analysis code.
9. Persistent Session
Refresh → research still exists.
10. Human Approval
Before consequential action.
11. One Real Action
Recommended:
Create GitHub experiment / GitHub issue.
12. Visible Agent Activity UI
Show the agent doing work.

32. DO NOT BUILD During MVP
Avoid:
Authentication system

Complex billing

Mobile app

Multiple research domains

Full knowledge graph

Enterprise permissions

Slack + Notion + Jira + GitHub simultaneously

Custom vector database architecture

Complex microservices

Perfect production infrastructure
Every unnecessary feature reduces polish.

33. Build Priority
Use this order:
1. TrueForge working
          ↓
2. One research question end-to-end
          ↓
3. Subagents
          ↓
4. Real sources
          ↓
5. Verification
          ↓
6. Decision generation
          ↓
7. Sandbox
          ↓
8. Human approval
          ↓
9. GitHub action
          ↓
10. Persistent sessions
          ↓
11. Beautiful UI
          ↓
12. Today's Radar
          ↓
13. Stretch features
Do not start with UI polish before the agent loop works.

34. Recommended Repository Structure
agentradar/
│
├── README.md
│
├── docs/
│   ├── architecture.md
│   ├── demo.md
│   └── decisions.md
│
├── apps/
│   │
│   ├── web/
│   │   ├── components/
│   │   ├── pages/
│   │   └── services/
│   │
│   └── api/
│       ├── routes/
│       ├── services/
│       └── models/
│
├── agents/
│   ├── orchestrator/
│   ├── news_scout/
│   ├── github_scout/
│   ├── paper_scout/
│   ├── docs_scout/
│   ├── verifier/
│   ├── signal_scorer/
│   └── synthesizer/
│
├── skills/
│   ├── research-methodology/
│   │   └── SKILL.md
│   │
│   ├── evidence-verification/
│   │   └── SKILL.md
│   │
│   └── decision-brief/
│       └── SKILL.md
│
├── tools/
│   ├── github/
│   ├── research/
│   └── scoring/
│
├── sandbox/
│   ├── signal_analysis.py
│   └── evidence_analysis.py
│
├── schemas/
│   ├── source.json
│   ├── claim.json
│   ├── signal.json
│   └── decision.json
│
└── tests/
Exact structure can change depending on TrueForge's recommended implementation.

35. Agent Skills
Three reusable skills would demonstrate strong agent engineering.
research-methodology
Rules such as:
Always search for primary sources.

For important claims, seek independent confirmation.

Prefer recent evidence for rapidly changing technologies.

Distinguish opinion from empirical evidence.

Record publication dates.

Detect when multiple articles reference
the same original source.
evidence-verification
Never assign high confidence from
a single marketing source.

Surface contradictory evidence.

Explain uncertainty.

Downgrade outdated evidence.

Separate measured results from claims.
decision-brief
Every final briefing must contain:

Verdict
Confidence
Why
Risks
Evidence
What changed
Impact on user
Remember
Recommended next action

36. Winning Demo Scenario
Use one scenario only.
Recommended question:
"Should our engineering team adopt MCP for new AI-agent integrations?"
Why:
    •    Current agent topic
    •    Easy to understand
    •    Multiple source types
    •    Architecture implications
    •    Fits target audience
    •    Leads naturally to an experiment

37. Three-Minute Demo Story
0:00–0:20 — Problem
Say:
"AI engineers have a strange problem. We have more information than ever, but making decisions is harder. Important evidence is scattered across papers, GitHub, documentation, announcements, benchmarks and community discussions."
Then:
"AgentRadar turns that information into a decision."

0:20–0:35 — Ask
Enter:
Should our engineering team adopt MCP
for new AI-agent integrations?
Click:
Start Research

0:35–1:10 — Show TrueForge Working
UI:
Research mission started.

✓ Research plan generated

● Documentation Agent
  Reading specification...

● GitHub Agent
  Measuring ecosystem activity...

● Research Agent
  Looking for independent evidence...

● News Agent
  Checking recent developments...

27 sources collected.
Do NOT skip this screen.
This demonstrates actual agency.

1:10–1:30 — Verification + Sandbox
Show:
Evidence verification

14 claims verified
2 claims contradicted
3 weak claims discarded

Running signal analysis...

[TrueForge Sandbox]
Then:
Signal Score: 9.0

Classification:
🔴 MAJOR SHIFT

1:30–2:05 — Decision Brief
Show the polished UI:
VERDICT

Adopt MCP for NEW integrations.

Do not rewrite stable integrations yet.

CONFIDENCE
█████████░ 91%

WHY

✓ ecosystem convergence
✓ reduced custom integration work
✓ increasing tool interoperability

RISKS

⚠ security practices still evolving
⚠ implementation quality varies

REMEMBER

"MCP standardizes how agents reach tools."
This is the visual wow moment.

2:05–2:20 — Personalization
Show:
Impact on your stack:

Python        HIGH
FastAPI       MEDIUM
LangGraph     HIGH
AWS           MEDIUM

Architecture impact:
8.7 / 10

2:20–2:40 — Recommended Action
AgentRadar:
Recommendation:

Don't migrate anything yet.

Run a controlled MCP experiment.

I can create it in GitHub.

[Create Experiment]
Click.

2:40–2:50 — Human Approval
Show:
AgentRadar wants to:

✓ Create experiment branch
✓ Generate test code
✓ Create README
✓ Open GitHub issue / PR

No production code will be modified.

[Cancel]        [Approve]
Pause.
Click Approve.

2:50–3:00 — Action + Closing
Show:
✓ Experiment created
✓ GitHub issue opened
✓ Research session saved
Then say:
"AgentRadar doesn't give engineers more AI news. It tells them what matters, why it matters to their system, and what to do next."
End.

38. Hackathon Strength Matrix
Area
AgentRadar Strategy
Potential impact
Engineering teams constantly face changing AI decisions
Originality
Signal-vs-hype + stack-aware intelligence + action
Technical excellence
Multi-agent evidence pipeline
Harness usage
TrueForge orchestrates entire workflow
Subagents
Multiple specialized researchers
Tools
Web + GitHub + external data
Sandbox
Evidence analysis and scoring
Persistence
Long-lived research missions
Safety
Approval before GitHub changes
UI
Visible agent execution + memorable briefs
Code quality
Structured repo + tests + Qodo PR workflow
Presentation
Single clear decision story

39. Our Main Competitive Advantage
Many teams may build:
Research Agent

Question
   ↓
Five searches
   ↓
Summary
We should NOT compete there.
Our competitive advantage is:
              LIVE INFORMATION
                     ↓
            SPECIALIST RESEARCH
                     ↓
               VERIFICATION
                     ↓
             SIGNAL VS HYPE
                     ↓
             STACK RELEVANCE
                     ↓
                DECISION
                     ↓
             MEMORY-FIRST UI
                     ↓
                ACTION
                     ↓
             HUMAN APPROVAL

40. The Single Most Important Product Insight
AgentRadar should optimize for:
Information compression without decision-quality loss.
Example:
62 sources

      ↓

8 developments

      ↓

3 signals

      ↓

1 decision

      ↓

1 action
That should be visually represented throughout the product.

41. Branding / Messaging
Name
AgentRadar
Tagline option 1
Know what matters in AI agents.
Tagline option 2
Signal, not noise.
Tagline option 3
From AI noise to engineering decisions.
Recommended:
AgentRadar
From AI noise to engineering decisions.

42. Landing Page Message
AI moves every day.

You don't need to read everything.

AgentRadar researches papers,
GitHub, documentation, benchmarks
and the live web.

It verifies the evidence,
separates signal from hype,
explains what matters to your stack,
and recommends what to do next.

                 [Start Research]

43. Success Criteria for the Hackathon
We consider the MVP successful if a judge can:
    1    Ask one real technology question.
    2    Watch multiple agents research it.
    3    See real external tools being called.
    4    See sources collected.
    5    See conflicting evidence handled.
    6    See code/data analysis execute in a sandbox.
    7    Receive a clear decision.
    8    Understand the decision in under 30 seconds.
    9    Ask AgentRadar to act on the recommendation.
    10    See the agent stop for approval.
    11    Approve the action.
    12    See the external action happen.
    13    Refresh the browser and recover the research session.
If all thirteen work reliably, stop adding major features and polish the demo.

44. Stretch Improvements
Only after the winning workflow works:
A. What Changed Since Yesterday?
You were away for 17 hours.

62 sources scanned.
8 developments found.
3 matter.
1 affects your stack.
B. Watchlists
Track:
MCP
LangGraph
OpenAI Agents SDK
A2A
CrewAI
Agent memory
Computer use
Agent security
C. Knowledge Map
Automatically connect concepts and developments.
D. Historical Signal Tracking
Show:
MCP SIGNAL

MAR   ███░░
APR   █████
MAY   ███████
JUN   ████████
AUG   ██████████
E. Daily Brief
Generate:
THE 3 THINGS THAT MATTER TODAY
F. Team Intelligence
One organization's technology stack produces personalized intelligence for the whole engineering team.

45. Future Business Model
AgentRadar could evolve into:
Technology intelligence infrastructure for engineering organizations.
Possible customers:
    •    AI startups
    •    SaaS companies
    •    engineering organizations
    •    VC technical teams
    •    CTO offices
    •    developer-platform teams
    •    enterprise AI teams
Possible pricing:
Individual
$20–40/month

Team
$100–500/month

Enterprise
Custom

Includes:

technology watchlists
team stack profiles
daily intelligence
decision reports
Slack integration
GitHub integration
custom research agents
Do not implement monetization during the hackathon.

46. Future Product Vision
Today:
AI Agent Intelligence
Later:
                 AgentRadar

                     │
       ┌─────────────┼─────────────┐
       │             │             │
    AI Agents      Security      Cloud
       │             │             │
      RAG        Vulnerabilities  AWS
      MCP        Dependencies     GCP
    Models          CVEs          Azure
Eventually:
Every engineering team has an autonomous technology analyst continuously watching the external world and understanding how changes affect its systems.

47. Final Pitch
10-second version
AgentRadar is an autonomous technology-intelligence agent that researches the rapidly changing AI-agent ecosystem, separates signal from hype, explains what matters to your stack, and turns important discoveries into approved actions.

30-second version
AI engineers are drowning in announcements, papers, GitHub releases, benchmarks, documentation and opinions. AgentRadar uses specialized research agents to investigate all of them, verify claims, identify meaningful signals, and explain exactly how a development affects your technology stack. Instead of giving you another long summary, it gives you a memorable decision brief and recommends what to do next. If you choose to act, AgentRadar can execute the next step through tools—but only after human approval.

48. Guiding Rule For The Team
Whenever we consider adding a feature, ask:
Does this help AgentRadar turn information into a better decision?
If the answer is no, we probably should not build it during the hackathon.
And whenever we consider adding complexity, ask:
Will this make the 3-minute demo noticeably better?
If the answer is no, postpone it.

49. North Star
The product should make this transformation possible:
BEFORE AGENTRADAR

50 tabs
12 articles
6 GitHub repositories
4 papers
3 conflicting opinions
2 hours of reading

            ↓

Still unsure.


AFTER AGENTRADAR

62 sources researched
14 claims verified
3 meaningful signals
1 clear recommendation

            ↓

Decision made.
AgentRadar
From AI noise to engineering decisions.