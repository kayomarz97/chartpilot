# Gemini API / google-genai SDK: verified facts for doctor_helper

Retrieved: 2026-08-20. All facts below were pulled from the LIVE official pages listed per
section (raw `curl` + manual grep of the HTML, not just search-snippet paraphrase, except
where noted "search-only / unverified"). Nothing here is from model memory.

**Big warning for anyone reading this after Jan 2026 knowledge cutoff:** Google has made two
large, non-obvious changes since then that will silently break code written from memory:

1. **"Vertex AI" branding/SDK param renamed.** The Google Gen AI Python SDK's Vertex mode
   constructor arg is now `enterprise=True` (not `vertexai=True`), and the product is now
   branded **"Gemini Enterprise Agent Platform"** in docs (`docs.cloud.google.com/gemini-enterprise-agent-platform/...`).
   The `Client.vertexai` property still exists in the SDK per the API reference index (kept
   for back-compat / read access), but the documented, current constructor kwarg in every
   code sample on `googleapis.github.io/python-genai` is `enterprise=True`. Env var is now
   `GOOGLE_GENAI_USE_ENTERPRISE=true` (previously `GOOGLE_GENAI_USE_VERTEXAI`).
2. **New "Interactions API" (GA) is now the recommended primary API surface**, replacing
   `generate_content` for new code. It changes the shapes for structured output and function
   calling (see §3, §4 below). `client.models.generate_content()` still exists in the SDK
   (confirmed present in current SDK docs, used for older single-shot calls, embeddings,
   tuning, etc.) but Google's own quickstart, structured-output, and function-calling guides
   now lead with `client.interactions.create()`. Treat `generate_content` as the lower-level/
   legacy-compatible path, `interactions.create()` as the currently-recommended path.

---

## 1. Model catalog (≥ Gemini 3.5)

Source: `https://ai.google.dev/gemini-api/docs/models` (page nav + sidebar path list),
`https://ai.google.dev/gemini-api/docs/changelog`. Read 2026-08-20.

Current models, exact API IDs (as used in `model=` param):

| Model ID | Status | Notes |
|---|---|---|
| `gemini-3.7-flash` | GA / Stable ("New Stable") | current default flagship-flash used throughout official examples |
| `gemini-3.6-flash` | GA (July 21, 2026) | "improved token efficiency and code/agentic planning ... lower price point than 3.5 Flash" |
| `gemini-3.5-flash` | GA (May 19, 2026) | "most intelligent model for sustained frontier performance on agentic and coding tasks" |
| `gemini-3.5-flash-lite` | GA (July 21, 2026) | "low-latency, highly cost-effective subagent option" |
| `gemini-3.1-flash-lite` | GA / Stable | |
| `gemini-3.1-pro-preview` | Preview | used in official function-calling-with-tools example (`model="gemini-3.1-pro-preview"`): **there is no GA "gemini-3.5-pro" or "gemini-3.6-pro" model ID as of 2026-08-20**; the Pro tier at 3.x is still preview-only (`gemini-3.1-pro-preview`, also saw `gemini-3-pro-preview`) |
| `gemini-3-flash-preview` | Preview | predecessor to 3.5-flash; changelog migration note: "Update model name: `gemini-3-flash-preview` → `gemini-3.5-flash`" |
| `gemini-3-pro-preview`, `gemini-3-pro-image` | Preview | image-capable variants exist too (`gemini-3.1-flash-image`, `gemini-3.1-flash-lite-image`) |

**Do not hardcode a model ID for anything long-lived**: Google explicitly deprecates preview
models with as little as 2 weeks' notice. For the hackathon, pin to `gemini-3.5-flash` or
`gemini-3.7-flash` (both GA/Stable as of 2026-08-20) but discover/validate at startup via
`client.models.list()` (below) and fail loudly if the configured ID is absent from the list.

### Runtime model discovery: `client.models.list()`

Source: `https://googleapis.github.io/python-genai/index.html`, section "List Base Models".

```python
for model in client.models.list():
    print(model)

# paginated
pager = client.models.list(config={'page_size': 10})
print(pager.page_size)
print(pager[0])
pager.next_page()

# async
async for job in await client.aio.models.list():
    print(job)
```

This works identically for both a Developer-API client and an `enterprise=True` client.
Use this to assert your configured `MODEL_ID` env var is actually present before running
the pipeline, instead of hardcoding a string with no verification.

---

## 2. SDK: package, install, client init, minimal call

Source: `https://ai.google.dev/gemini-api/docs/quickstart`,
`https://googleapis.github.io/python-genai/index.html`. Read 2026-08-20.

**Package name:** `google-genai` (import path `from google import genai`). This is the
official "Google Gen AI SDK": same package serves both Gemini Developer API and the
Gemini Enterprise Agent Platform (formerly "Vertex AI") backends; you select which backend
via constructor args.

**Install:**
```bash
pip install -U google-genai
# or
uv pip install google-genai
```
**Pinned-version recommendation:** current latest on PyPI as of 2026-08-20 is
`google-genai==2.18.1` (released 2026-08-13, per `https://pypi.org/pypi/google-genai/json`).
Pin this exact version in `pyproject.toml`/`requirements.txt` for hackathon reproducibility;
re-check before demo day since this SDK ships frequently.

**(a) Developer API client (API key):**
```python
from google import genai
client = genai.Client(api_key='GEMINI_API_KEY')
# or rely on env var GEMINI_API_KEY / GOOGLE_API_KEY (GOOGLE_API_KEY wins if both set)
client = genai.Client()
```

**(b) Enterprise/Vertex-mode client (project + location):**
```python
from google import genai
client = genai.Client(
    enterprise=True, project='your-project-id', location='us-central1'
)
```
Env-var form:
```bash
export GOOGLE_GENAI_USE_ENTERPRISE=true
export GOOGLE_CLOUD_PROJECT='your-project-id'
export GOOGLE_CLOUD_LOCATION='us-central1'
```
```python
from google import genai
client = genai.Client()
```

**Minimal generate-content call (classic/legacy-compatible path, still supported):**
```python
response = client.models.generate_content(
    model='gemini-3.5-flash', contents='Why is the sky blue?'
)
print(response.text)
```

**Minimal call via the now-recommended Interactions API:**
```python
from google import genai
client = genai.Client()
interaction = client.interactions.create(
    model="gemini-3.7-flash",
    input="Explain how AI works in a few words"
)
print(interaction.output_text)
```
Streaming: pass `stream=True` to `interactions.create(...)` and iterate the returned
generator of SSE-style events (`step.start` / `step.delta` / `step.stop`).

**Explicit resource cleanup** (sync and async), per SDK docs:
```python
client.close()
# or
with genai.Client() as client:
    ...
# async: await client.aio.aclose() / async with genai.Client().aio as aclient: ...
```

**API version selection** (beta endpoints are default; pin to stable `v1` if desired):
```python
from google.genai import types
client = genai.Client(
    enterprise=True, project='p', location='us-central1',
    http_options=types.HttpOptions(api_version='v1')
)
```

---

## 3. Structured output (JSON schema / Pydantic)

Source: `https://ai.google.dev/gemini-api/docs/structured-output`. Read 2026-08-20 (raw HTML
grepped; verified zero occurrences of `response_schema`/`response_mime_type` anywhere on the
current page: those are the OLD `generate_content`-era param names and are **not** what the
current docs show for the Interactions API path).

**Current, documented shape (Interactions API):** `response_format` dict with keys
`type`, `mime_type`, `schema`. Pydantic `BaseModel.model_json_schema()` is directly supported
for the `schema` value.

```python
from google import genai
from pydantic import BaseModel, Field
from typing import List, Optional

class Ingredient(BaseModel):
    name: str = Field(description="Name of the ingredient.")
    quantity: str = Field(description="Quantity of the ingredient, including units.")

class Recipe(BaseModel):
    recipe_name: str = Field(description="The name of the recipe.")
    prep_time_minutes: Optional[int] = Field(description="Optional prep time in minutes.")
    ingredients: List[Ingredient]

client = genai.Client()
interaction = client.interactions.create(
    model="gemini-3.7-flash",
    input=prompt,
    response_format={
        "type": "text",
        "mime_type": "application/json",
        "schema": Recipe.model_json_schema()
    },
)
recipe = Recipe.model_validate_json(interaction.output_text)
```

Union/discriminated types are supported (`Union[SpamDetails, NotSpamDetails]` example in
docs). Streaming structured output is supported (`stream=True` + same `response_format`).
Gemini 3 lets you combine Structured Outputs with built-in tools (Google Search, code
execution, url_context) in the same call: shown with `model="gemini-3.1-pro-preview"` in
the docs' own example (note: that example uses a **preview** Pro model, since no GA 3.5/3.6
Pro model ID exists yet).

**Gap/ambiguity flagged:** The docs page I read does not show the equivalent `response_schema`/
`response_mime_type` kwargs for the older `client.models.generate_content()` call path on
Gemini 3.x models. If the codebase ends up needing structured output through
`generate_content` (not `interactions.create`) specifically, re-verify against
`googleapis.github.io/python-genai` reference docs for `GenerateContentConfig` before relying
on memory of the old `response_schema=` kwarg. Do not assume it is unchanged.

---

## 4. Function/tool calling + thought signatures (Gemini 3.x)

Source: `https://ai.google.dev/gemini-api/docs/function-calling`,
`https://ai.google.dev/gemini-api/docs/thinking` (thought signatures section, anchor
`#signatures`; the old URL `/gemini-api/docs/thought-signatures` redirects here). Read
2026-08-20.

**Tool declaration + call (Interactions API shape):**
```python
weather_function = {
    "type": "function",
    "name": "get_weather",
    "description": "Gets the current weather for a location.",
    "parameters": {
        "type": "object",
        "properties": {"location": {"type": "string"}},
        "required": ["location"],
    },
}

interaction = client.interactions.create(
    model="gemini-3.7-flash",
    input="What's the temperature in London?",
    tools=[weather_function],
)

fc_step = next(s for s in interaction.steps if s.type == "function_call")
# fc_step.name, fc_step.arguments, fc_step.id
result = my_fn(**fc_step.arguments)

final_interaction = client.interactions.create(
    model="gemini-3.7-flash",
    input=[{
        "type": "function_result",
        "name": fc_step.name,
        "call_id": fc_step.id,
        "result": [{"type": "text", "text": json.dumps(result)}],
    }],
    tools=[weather_function],
    previous_interaction_id=interaction.id,   # stateful continuation
)
print(final_interaction.output_text)
```
Tool-choice control: `generation_config={"tool_choice": "auto" | "any" | "none"}`.
Parallel function calling: model can emit multiple `function_call` steps in one turn.

**Thought signatures: exact requirements (quoted from the Thinking guide):**

> "Thought signatures are encrypted representations of the model's internal reasoning. They
> are required to maintain reasoning continuity across multi-turn interactions."

- **Stateful mode (recommended):** set `store: true` and pass `previous_interaction_id` on
  the next turn. *"the server automatically manages the conversation state, including all
  thought blocks and signatures. In this mode, you do not need to do anything regarding
  signatures. They are handled entirely on the server side."*
- **Stateless mode** (you manage history client-side, `store=false`):
  - *"You **MUST** always resend all thought blocks exactly as they were received from the
    model."*
  - *"You should **NOT** remove or modify thought blocks from the history, as they contain
    the signatures required for the model to continue its reasoning."*
  - When switching models mid-session, still resend the previous model's thought blocks:
    "the backend manages compatibility."
  - Built-in tool steps (e.g. `google_search_call`/`google_search_result`) can carry their
    own signatures too and must also be resent in stateless mode.
- Signature location differs by API: in `generateContent`, signatures are metadata attached
  to arbitrary parts (e.g. inside `functionCall` parts). In the Interactions API, signatures
  live only on dedicated `thought` steps or built-in-tool steps, never on user input, model
  text output, or plain `function_call` steps.
- **SDK auto-handling:** *"Gemini 3 series models use an internal 'thinking' process that
  improves function calling. The SDKs automatically handle thought signatures for you"* when
  you use the SDK's own chained-turn convenience pattern (append `interaction.steps` /
  `step.model_dump()` to a running history list and resend as `input` on the next call, as
  shown in the docs' stateless-mode example), i.e. the SDK does not silently strip
  signatures if you round-trip `step` objects as given, but it does not manage state for you
  across process restarts; **your application must persist and replay the full `steps`
  list** if you are not using `previous_interaction_id` server-side state.
- **Function calling strict response matching (Gemini 3.x specific):** `id`, `name`, and
  response count on function-result steps must match the preceding `function_call` steps
  exactly, or the Interactions API errors. (Source: `whats-new-gemini-3.5` migration guide.)

**Decision-relevant for a Cloud-Tasks-driven durable pipeline:** since Cloud Tasks workers are
stateless between invocations, prefer **stateful mode** (`store: true` +
`previous_interaction_id` persisted in your own app DB) so Google's servers hold the thought
history: this avoids having to serialize/deserialize full `steps` arrays including opaque
signature blobs in your own storage. If you must go stateless (e.g. to avoid any server-side
retention), you must store and replay the entire `steps` array verbatim, including `thought`
steps, and must not truncate/summarize them.

---

## 5. Sampling / determinism guidance for Gemini 3.x

Source: `https://ai.google.dev/gemini-api/docs/whats-new-gemini-3.5` ("Parameter updates and
best practices in Gemini 3.x" / "Sampling parameters (no longer recommended)" sections), and
changelog entry dated **July 21, 2026**. Read 2026-08-20 (raw HTML verified).

> "`temperature`, `top_p`, and `top_k` are no longer recommended for all Gemini 3.x models.
> Gemini 3's reasoning capabilities are optimized for the default settings. Remove these
> parameters from all requests."
>
> "To ensure determinism, we recommend defining a system instruction with explicit rules for
> your specific use case."

Changelog (2026-07-21) formally lists this as: *"Deprecated parameters: The sampling
parameters `temperature`, `top_p` and `top_k` are now deprecated."*

Also deprecated/changed alongside: raw numeric `thinking_budget` → replaced by
`thinking_level` string enum (`minimal` | `low` | `medium` (default) | `high`), set via
`generation_config={"thinking": {"thinking_level": "medium"}}`. Default effort changed from
`high` → `medium` between 3.x versions; re-test prompt quality after upgrading model IDs.
"Thought preservation is now on by default" for Gemini 3.x: reasoning context carries
forward across turns automatically (increases token usage but improves performance).

**Practical guidance for doctor_helper:** do not set `temperature`/`top_p`/`top_k` on Gemini
3.x calls at all (neither to force determinism nor to add variance), Google's own guidance
says removing them entirely, not pinning `temperature=0`, is the recommended posture. If the
existing TECHNICAL_DECISIONS.md "sampling-param gate" assumed `temperature=0` for
determinism, that assumption should be revised: use fixed system instructions / schema
constraints for determinism instead, and confirm this policy is scoped to the Gemini client
only (a non-Gemini Model B such as another vendor's model may legitimately still use temperature).

---

## 6. Agent frameworks: ADK vs GenAI SDK

Source: `https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/adk` (fetched
2026-08-20, note: "Vertex AI Agent Builder" docs have also moved under the
"Gemini Enterprise Agent Platform" branding) + general framework description corroborated by
`developers.googleblog.com` ADK launch post (search-verified, not raw-fetched, treat framing
as directionally correct, verify exact API signatures separately if ADK is actually adopted).

**Google ADK (Agent Development Kit):** An opinionated, higher-level Python (also
TS/Go/Java) framework for building and orchestrating *multi-agent* systems: it ships agent
classes, workflow primitives (`SequentialAgent`, `ParallelAgent`, `LoopAgent` for
deterministic pipelines, or LLM-router agents for dynamic routing), a tool ecosystem, and
first-class deploy targets (Agent Engine / Cloud Run / GKE via `adk deploy`). It is the
heavier choice: you adopt ADK's own agent/session/state abstractions, not just an SDK call.
Best fit when you want Google's opinions about how agents coordinate and you're fine ceding
orchestration control to its runtime.

**google-genai (GenAI SDK):** A thin, unopinionated client library for calling Gemini models
(chat, tools, structured output, streaming) with no imposed orchestration model: you own all
state, retries, and pipeline logic yourself (e.g. with Cloud Tasks + your own app DB, as
doctor_helper's architecture already does). This is the lighter-weight choice for "we own
orchestration."

**For a small durable pipeline where the app owns orchestration via Cloud Tasks + app
state:** `google-genai` alone is the better technical fit: adopting ADK on top would mean
fighting or duplicating ADK's own state/session model against your Cloud Tasks state machine.

**Does using `google-genai` alone satisfy the hackathon's "Google Agent Framework" bullet?**
The hackathon rule lists four qualifying options: *"Google ADK, GenAI SDK, Antigravity SDK,
or GenKit."* **"GenAI SDK" is listed as its own qualifying option, separate from ADK**, and
`google-genai` is literally and officially named "Google Gen AI SDK" per its own docs title
(`googleapis.github.io/python-genai` → "Google Gen AI SDK documentation"). So yes: using
`google-genai` for model calls, tool calling, and structured output satisfies the "GenAI SDK"
branch of the requirement on its own; ADK is not required in addition. (This is a
requirements-interpretation, not a Google doc fact, flagging it as such. If the hackathon
rules committee has their own stricter interpretation, that overrides this reading.)

---

## 7. Rate limits / free tier

Source: `https://ai.google.dev/gemini-api/docs/rate-limits`. Read 2026-08-20 (raw HTML).

**Important finding: the public rate-limits page no longer publishes static per-model
RPM/TPM/RPD numbers for the Free/Tier-1/etc. tiers.** It now says:

> "Rate limits depend on a variety of factors (such as your usage tier) and can be viewed in
> Google AI Studio." → links to `https://aistudio.google.com/rate-limit`
>
> "Specified rate limits are not guaranteed and actual capacity may vary."

What the page *does* state concretely:
- **Usage tiers:** Free (active project or free trial, no billing cap) → Tier 1 (billing
  linked, $250 cap) → Tier 2 (after $100 cumulative spend + 3 days, $2,000 cap) → Tier 3
  (after $1,000 spend + 30 days, $20,000-$100,000+ cap). Tiers upgrade automatically as
  cumulative Google Cloud billing-account spend increases.
- **Spend-based rate limit** (rolling 10-minute window, separate from RPM/TPM): Free = N/A,
  Tier 1 = $10 / 10 min, Tier 2 = $50 / 10 min, Tier 3 = $200 / 10 min. Exceeding it returns
  HTTP 429 `RESOURCE_EXHAUSTED`.
- Rate limits are **per project**, not per API key; RPD quotas reset at midnight Pacific.
- Preview/experimental models get more restrictive limits than GA models.
- Priority inference has its own limit: 0.3x the standard rate limit per model/tier.
- Batch API: 100 concurrent batch requests, 2GB input file limit, 20GB file storage limit,
  and per-model enqueued-token caps (Tier 1 examples seen on page: Gemini 3.7 Flash =
  3,000,000 tokens; Gemini 3.6 Flash = 3,000,000; Gemini 3.5 Flash = 3,000,000; Gemini 3.5
  Flash-Lite = 10,000,000; Gemini 3.1 Pro Preview = 5,000,000; Gemini 3.1 Flash Lite =
  10,000,000).

**Gap flagged:** I could not find a live official page giving exact numeric RPM/TPM/RPD for
the Free tier on `gemini-3.5-flash` etc., Google appears to have moved this to a
per-project, dynamically-computed dashboard (AI Studio "rate-limit" page) rather than a
static docs table, likely because it now varies by account signals. **Do not hardcode
specific Free-tier RPM/TPM numbers from third-party blogs (aifreeapi.com, aipromptshub.co,
etc.) into code or planning docs; they are unverified and not from ai.google.dev.** For the
hackathon, check `https://aistudio.google.com/rate-limit` directly with the actual project's
API key before sizing concurrency/backoff logic, and build retry/backoff around HTTP 429
regardless of the exact number.

---

## Sources (all read 2026-08-20)

- https://ai.google.dev/gemini-api/docs/models
- https://ai.google.dev/gemini-api/docs/quickstart
- https://ai.google.dev/gemini-api/docs/changelog
- https://ai.google.dev/gemini-api/docs/whats-new-gemini-3.5
- https://ai.google.dev/gemini-api/docs/structured-output
- https://ai.google.dev/gemini-api/docs/function-calling
- https://ai.google.dev/gemini-api/docs/thinking (thought signatures section; old URL
  `/gemini-api/docs/thought-signatures` now redirects here)
- https://ai.google.dev/gemini-api/docs/rate-limits
- https://googleapis.github.io/python-genai/index.html (Google Gen AI SDK reference/guide)
- https://pypi.org/pypi/google-genai/json (version pin check)
- https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/adk (ADK, current
  branding, formerly under Vertex AI docs)
