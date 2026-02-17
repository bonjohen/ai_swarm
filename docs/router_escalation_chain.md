```markdown
# PDR.MD — Tiered Local Inference Router with Regex, Dual 1.5B Instances, and Progressive Escalation

---

# 1. Purpose

Design and implement a **cost-aware, quality-aware, tiered inference control plane** that:

1. Uses deterministic routing first (regex / command layer).
2. Uses two specialized local 1.5B instances:
   - Micro Router Instance
   - Light Reasoning Instance
3. Escalates to progressively more capable AI models only when necessary.
4. Makes routing decisions based on measurable cost and quality characteristics.
5. Logs and learns from routing outcomes over time.

This router becomes the central nervous system for:
- Certification Engine
- Dossier System
- Story World Engine
- AI Lab
- Tool calling
- Script execution

---

# 2. Design Philosophy

The system must:

- Minimize frontier usage.
- Avoid using LLMs for deterministic tasks.
- Separate classification from reasoning.
- Separate light reasoning from heavy reasoning.
- Use structured confidence metrics.
- Be explainable and auditable.

This is not just a router.
It is a **tiered cognitive control system**.

---

# 3. Tiered Architecture Overview

```

Incoming Request
↓
Tier 0 — Deterministic Regex Layer
↓
Tier 1 — Micro LLM (Instance A)
↓
Tier 2 — Light LLM (Instance B)
↓
Tier 3 — Frontier Model

```

Each tier has:
- Cost profile
- Latency profile
- Capability profile
- Escalation criteria

---

# 4. Tier 0 — Deterministic Layer

## 4.1 Purpose

Handle all requests that can be resolved without an LLM.

## 4.2 Responsibilities

- Slash command parsing
- CLI-style directives
- Script execution
- Static tool routing
- JSON schema detection
- Known command mapping
- Pattern-based classification

## 4.3 Examples

```

/run test_suite
/story new_episode
/cert build az-104
/lab benchmark qwen

```

Regex handles:
- `/[a-z_]+`
- structured JSON payloads
- known system directives

## 4.4 Output Format

```

{
"handled": true,
"action": "execute_script",
"target": "run_cert.py",
"confidence": 1.0
}

```

## 4.5 Escalation

If no deterministic match:
→ Pass to Tier 1.

---

# 5. Tier 1 — Micro LLM (Instance A)

## 5.1 Model Characteristics

- 1.5B parameter model (quantized Q4/Q5)
- Context: 1–2k
- Max tokens: ≤128
- Temperature: 0–0.2
- Strict JSON output
- Deterministic sampling preferred

Optimized for:
- Speed
- Concurrency
- Structured classification

## 5.2 Responsibilities

- Intent classification
- Tool selection
- Skill routing
- Complexity estimation
- Safety flagging
- JSON schema enforcement

## 5.3 Output Contract

```

{
"intent": "story_generation",
"requires_reasoning": true,
"complexity_score": 0.42,
"confidence": 0.87,
"recommended_tier": 2
}

```

## 5.4 Escalation Rules

Escalate to Tier 2 if:

- `requires_reasoning == true`
- `complexity_score > 0.35`
- `confidence < 0.75`
- structured validation fails twice

Otherwise:
→ Execute tool or return output directly.

---

# 6. Tier 2 — Light LLM (Instance B)

## 6.1 Model Characteristics

- Same 1.5B base or slightly larger small model
- Context: 4k
- Max tokens: 512–1024
- Temperature: 0.2–0.5
- Allows short reasoning chains

Optimized for:
- Low-cost reasoning
- Short synthesis
- Scene drafting
- Summarization
- Multi-tool planning

## 6.2 Responsibilities

- Short reasoning chains
- Scene writing
- Dossier summaries
- Certification module drafting
- Multi-step tool selection
- Constraint enforcement

## 6.3 Output Contract

```

{
"result": "...",
"reasoning_depth_estimate": 2,
"confidence": 0.82,
"quality_score": 0.78,
"escalate": false
}

```

## 6.4 Escalation Criteria to Tier 3

Escalate if:

- `reasoning_depth_estimate > 3`
- `quality_score < threshold`
- user explicitly requests high precision
- task classified as:
  - long context (>4k tokens)
  - multi-document synthesis
  - high emotional nuance
  - legal/financial correctness critical

---

# 7. Tier 3 — Frontier Model

## 7.1 Characteristics

- High capability
- High cost
- Large context
- Advanced reasoning

Used only when:
- Required by complexity
- Local confidence low
- Task demands high nuance or accuracy

---

# 8. Cost & Quality Model

## 8.1 Cost Metrics

Track per request:

- tokens_in
- tokens_out
- latency_ms
- $ cost (frontier only)
- VRAM usage (local)
- GPU utilization

## 8.2 Quality Metrics

Structured metrics:

- confidence_score
- JSON_validity (boolean)
- contradiction_flag (boolean)
- reasoning_depth_estimate
- hallucination_risk_score
- policy_violation_flag

## 8.3 Composite Routing Score

Compute:

```

routing_score =
(complexity_score * weight1) +
((1 - confidence) * weight2) +
(hallucination_risk * weight3)

```

Escalate when `routing_score > threshold`.

---

# 9. Dual Instance Configuration

## 9.1 Instance A — Micro Router

Configuration:

- Q4 quant
- Context 2k
- Max tokens 128
- Temperature 0
- High concurrency

Purpose:
Fast, structured decisions.

---

## 9.2 Instance B — Light Reasoner

Configuration:

- Q4 or Q5 quant
- Context 4k
- Max tokens 512–1024
- Slight temperature
- Moderate concurrency

Purpose:
Short reasoning and synthesis.

---

# 10. GPU Strategy (RTX 4070)

VRAM strategy:

- Keep both models loaded persistently.
- Reserve 2–3GB headroom.
- Cap context sizes.
- Monitor KV cache.

Concurrency approach:

- Use unified inference engine (preferred) OR
- Two separate services pinned to GPU with controlled worker pools.

---

# 11. Routing Decision Algorithm (High-Level)

```

function route(request):

if regex_match(request):
return execute_deterministic()

tier1_result = micro_model(request)

if tier1_result.recommended_tier == 1:
return execute_tool()

if tier1_result.recommended_tier == 2:
tier2_result = light_model(request)

```
  if tier2_result.escalate:
      return frontier_model(request)

  return tier2_result.result
```

return frontier_model(request)

```

---

# 12. Observability & Logging

For each request log:

- initial intent
- chosen tier
- escalation reason
- cost
- latency
- confidence score
- failure modes

This allows:

- Threshold tuning
- Cost optimization
- Performance regression detection

---

# 13. Safety & Reliability

- Deterministic validation of JSON outputs.
- Retry policy at each tier.
- Fallback to deterministic tool execution if LLM classification fails.
- Timeout enforcement.
- Hard cap on frontier usage per day.

---

# 14. Failure Handling

If Tier 1 fails:
- Retry once.
- If still invalid → escalate to Tier 2.

If Tier 2 fails:
- Retry with stricter constraints.
- If still invalid → escalate to Tier 3.

If Tier 3 fails:
- Return structured error object.
- Do not silently degrade quality.

---

# 15. Extension Points

Future improvements:

- Dynamic threshold learning from outcomes.
- Confidence calibration based on historical accuracy.
- Model A/B routing experiments.
- Model swap without changing routing logic.
- Load-based dynamic routing (if GPU saturated).

---

# 16. Expected Outcomes

This system:

- Minimizes frontier spend.
- Maximizes local autonomy.
- Provides predictable latency.
- Creates structured escalation logic.
- Supports your multi-engine AI factory.

It becomes a programmable cognitive ladder.

---

If desired next, I can:
- Add numerical threshold defaults
- Provide concurrency estimates for 4070
- Convert this into an implementation-ready router.yaml
- Or design a cost simulation model
```
