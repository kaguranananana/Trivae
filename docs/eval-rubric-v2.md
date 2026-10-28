# Eval rubric v2

Judge v2 is the versioned review rubric for saved Agent answers. Its version identifier is `eval-rubric-v2`; the previous five-axis rules remain available as `JUDGE_V1_PROMPT` and historical v1 Review records stay under `eval-rubric-v1`.

## Scoring dimensions

Each dimension is scored independently from 0 to 4, or `unknown` when the available material cannot support a reliable judgment. `unknown` is excluded from the numeric mean and is never treated as zero.

### Task satisfaction

Judge whether the answer understood and resolved the user's request, covered its central requirements, and omitted anything important.

| Score | Boundary |
| --- | --- |
| 4 | Resolves the request and covers every substantive requirement. Only harmless details or presentation issues remain. |
| 3 | Resolves the core request and covers the important needs. Any omissions or defects are slight and do not block understanding or action. |
| 2 | Provides useful partial help but has a noticeable omission or misses an important subrequest, leaving the user to infer, ask again, or do a key step. |
| 1 | Misses most of the core need, substantially strays from the request, or has very little practical value. |
| 0 | Makes no effective attempt or a key omission prevents the user's goal from being met. |
| unknown | The question or answer is missing or too incomplete to judge satisfaction reliably. |

### Answer reliability

Judge whether key facts are correct, evidence supports the conclusions, and attribution, time, and scope are accurate. Lack of evidence is not proof that a claim is false. An unsupported claim must be distinguished from a contradicted claim and from information that was not retrieved.

| Score | Boundary |
| --- | --- |
| 4 | Key facts are correct and supported; citations, attribution, time, and scope fit. No material unsupported claims remain. Harmless wording imperfections do not lower the score. |
| 3 | The main conclusion is trustworthy and adequately supported. Only a minor imprecision or noncritical support gap remains. |
| 2 | A factual, citation, support, attribution, time, or scope issue materially affects part of the answer, while substantial reliable content remains. |
| 1 | The main conclusion is seriously unreliable due to a key factual error, evidence mismatch, attribution/scope failure, or several important unsupported claims. |
| 0 | A severe key error, fabricated evidence, or seriously misleading central conclusion makes the answer unreliable. |
| unknown | Crucial evidence is unavailable and the dimension cannot be scored reliably from the supplied material. |

## Diagnostics

Each specific issue records one primary dimension so the same problem is not mechanically deducted in both dimensions. A diagnostic contains a type, severity (`minor`, `moderate`, `severe`), exact answer excerpt (or `null` for an omission), supporting raw evidence or an explicit evidence gap, and its practical impact. Supported evidence outside the reference-fact list remains acceptable.

The supported issue types are `omitted_key_information`, `factual_error`, `attribution_error`, `citation_mismatch`, `unsupported_assertion`, `temporal_or_scope_error`, and `other`. No diagnostic is emitted when the judge finds no concrete issue.

The output is one `EvaluationReview` with two numeric/unknown axes and structured diagnostics. No percentage, weighted total, additional model review, Agent execution, or retrieval pass is part of this rubric. A review is flagged for human adjudication when either dimension is `unknown` or 0–2, or any moderate/severe issue is present. This also surfaces a possible mismatch when a passing score coexists with a material diagnosis.

## Evidence rules

The question, full answer, frozen cited messages, reference facts, and evidence limitations are provided together. References are open-ended, not a required message-ID checklist. Judge distinguishes evidence that supports a claim, evidence that contradicts it, and evidence that is absent or insufficient. Message time and scope are evaluated in context; old chat messages do not establish that prices, offers, or product details remain current. Structured SQL values are not treated as re-executed source evidence.
