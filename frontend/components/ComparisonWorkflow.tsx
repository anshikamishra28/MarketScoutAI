"use client";

import { useState, type FormEvent } from "react";
import { confirmComparisonWorkflow, getComparisonWorkflow, startComparisonWorkflow } from "../lib/api";
import type { AttributeDefinition, ComparisonWorkflowIssue, ComparisonWorkflowResponse, EntityReference } from "../types/comparison";

interface Props { busy: boolean; error: string; onRequestStarted: () => void; onExecutionStarted: (id: string, status: string) => void }
const commonAttributes = ["Price", "Quality", "Availability", "Specifications"];

function requestKey(value: string, prefix: string): string {
  const key = value.toLocaleLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
  return /^[a-z]/.test(key) ? key : `${prefix}_${key || prefix}`;
}

function attributeType(label: string): AttributeDefinition["value_type"] {
  if (/\b(price|cost|fee|charge)\b/i.test(label)) return "scalar";
  if (/\b(availability|stock)\b/i.test(label)) return "categorical";
  return "structured";
}

function isTechnical(value: string): boolean {
  return value.includes("/") || /value_type|comparison_rule|provenance|intent|identifier|source adapter|USER_CONFIRMED|USER_PROVIDED|PROPOSED|^\w+_[A-Z_]+$/.test(value);
}
function friendlyQuestion(issue: ComparisonWorkflowIssue, products: string[]): string {
  const text = issue.clarification_question || issue.message || "";
  if (/source/i.test(`${text} ${issue.code}`)) return "No verified shopping source is available for this comparison right now.";
  if (/attribute|value_type|comparison_rule/i.test(`${text} ${issue.code} ${issue.target}`)) return "What would you like us to compare about these products?";
  const quoted = text.match(/[“'\"]([^”'\"]+)[”'\"]/);
  const item = quoted?.[1] || products[0] || "this product";
  if (/version|variant|identified|identity|model|ambiguous|entity/i.test(`${text} ${issue.code} ${issue.target}`) || isTechnical(text)) return `Which version of ${item} do you mean?`;
  return text && !isTechnical(text) ? text : "Which product detail should we use?";
}
function safeCandidates(issue: ComparisonWorkflowIssue): string[] {
  return issue.candidates.filter((candidate): candidate is string => typeof candidate === "string" && !!candidate.trim() && !isTechnical(candidate));
}

export function ComparisonWorkflow({ busy, error, onRequestStarted, onExecutionStarted }: Props) {
  const [category, setCategory] = useState("");
  const [products, setProducts] = useState(["", ""]);
  const [selected, setSelected] = useState<string[]>(commonAttributes);
  const [otherAttributes, setOtherAttributes] = useState("");
  const [clarificationAnswer, setClarificationAnswer] = useState("");
  const [session, setSession] = useState<ComparisonWorkflowResponse | null>(null);
  const [reviewed, setReviewed] = useState(false);
  const [loading, setLoading] = useState(false);
  const [requestError, setRequestError] = useState("");

  function show(result: ComparisonWorkflowResponse) {
    setRequestError("");
    setSession(result);
    setReviewed(false);
    if (result.comparison_id) onExecutionStarted(result.comparison_id, result.comparison_status ?? "queued");
  }

  function makeRequest(extraAnswer = ""): string {
    const attributes = [...selected, ...otherAttributes.split(",").map((item) => item.trim()).filter(Boolean)];
    const categoryText = category.trim() ? ` in the ${category.trim()} category` : "";
    const answerText = extraAnswer.trim() ? `. ${extraAnswer.trim()}` : "";
    return `Compare ${products[0].trim()} with ${products[1].trim()}${categoryText} by ${[...new Set(attributes)].join(", ")}${answerText}.`;
  }

  function structuredRequest(): { entities: EntityReference[]; attributes: AttributeDefinition[] } {
    const usedEntityKeys = new Set<string>();
    const entities = products.map((product, index) => {
      const display_name = product.trim();
      const base = requestKey(display_name, `entity_${index + 1}`);
      let key = base;
      let suffix = 2;
      while (usedEntityKeys.has(key)) key = `${base}_${suffix++}`;
      usedEntityKeys.add(key);
      return { key, display_name, identifiers: {}, aliases: [] };
    });
    const labels = [...new Set([...selected, ...otherAttributes.split(",").map((item) => item.trim()).filter(Boolean)])];
    const usedAttributeKeys = new Set<string>();
    const attributes = labels.map((label, index) => {
      const base = requestKey(label, `attribute_${index + 1}`);
      let key = base;
      let suffix = 2;
      while (usedAttributeKeys.has(key)) key = `${base}_${suffix++}`;
      usedAttributeKeys.add(key);
      return { key, label, value_type: attributeType(label) };
    });
    return { entities, attributes };
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!products[0].trim() || !products[1].trim()) return;
    await interpret(makeRequest());
  }

  async function interpret(userRequest: string) {
    setLoading(true); setSession(null); setRequestError(""); onRequestStarted();
    try {
      show(await startComparisonWorkflow({
        user_request: userRequest,
        context: category.trim() ? { category: category.trim() } : {},
        source_preferences: [],
        ...structuredRequest(),
      }));
      setClarificationAnswer("");
    } catch (reason) {
      setSession(null); setRequestError(reason instanceof Error ? reason.message : "We couldn't prepare this comparison. Please try again.");
    } finally { setLoading(false); }
  }

  async function continueClarification(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!clarificationAnswer.trim()) return;
    await interpret(makeRequest(clarificationAnswer));
  }

  async function confirmInterpretation() {
    if (!session || !reviewed) return;
    const values = Object.fromEntries(session.clarification.confirmations_required.map((item) => [item.path, item.proposed_value]));
    setLoading(true); setRequestError("");
    try {
      const updated = await confirmComparisonWorkflow(session.workflow_id, { values });
      show(await getComparisonWorkflow(updated.workflow_id));
    } catch (reason) {
      setRequestError(reason instanceof Error ? reason.message : "We couldn't continue this comparison. Please review your request.");
    } finally { setLoading(false); }
  }

  const entities = session?.intent.request.entities ?? [];
  const attributes = session?.intent.request.attributes ?? [];
  const issues = session?.clarification.unresolved ?? [];
  const needsSource = issues.some((issue) => /source/i.test(`${issue.code} ${issue.target} ${issue.message} ${issue.clarification_question ?? ""}`));
  const questions = issues.filter((issue) => !/source/i.test(`${issue.code} ${issue.target} ${issue.message} ${issue.clarification_question ?? ""}`));
  const confirmations = session?.clarification.confirmations_required ?? [];
  const awaitingConfirmation = confirmations.length > 0;

  return <section className="workspace comparison-workflow" aria-labelledby="compare-title">
    <header className="comparison-intro"><p className="eyebrow">MARKET COMPARISON</p><h1 id="compare-title">Compare Products</h1><p>Compare two products side by side.</p></header>
    <form className="simple-comparison-form" onSubmit={submit}>
      <label>Category <input value={category} onChange={(event) => setCategory(event.target.value)} placeholder="Chocolate, laptop, headphones..." disabled={loading || busy} /></label>
      <div className="comparison-product-fields">{products.map((product, index) => <label key={index}>Product {index + 1}<input value={product} onChange={(event) => setProducts((current) => current.map((value, item) => item === index ? event.target.value : value))} placeholder="Enter a product" required disabled={loading || busy} /></label>)}</div>
      <fieldset className="attribute-picker"><legend>Compare by</legend><div>{commonAttributes.map((attribute) => <label key={attribute} className={`attribute-chip ${selected.includes(attribute) ? "selected" : ""}`}><input type="checkbox" checked={selected.includes(attribute)} onChange={(event) => setSelected((current) => event.target.checked ? [...current, attribute] : current.filter((item) => item !== attribute))} disabled={loading || busy} />{attribute}</label>)}</div><label className="custom-attribute-label">Other things to compare (optional)<input value={otherAttributes} onChange={(event) => setOtherAttributes(event.target.value)} placeholder="Taste, ingredients, battery life, camera, etc." disabled={loading || busy} /></label></fieldset>
      {(!selected.length && !otherAttributes.trim()) && <p className="form-hint">Choose at least one comparison attribute.</p>}
      {(error || requestError) && <p className="generic-error" role="alert">We couldn't prepare this comparison. Please try again.</p>}
      <button className="generic-submit" type="submit" disabled={loading || busy || !products[0].trim() || !products[1].trim() || (!selected.length && !otherAttributes.trim())}>{loading || busy ? "Comparing products..." : "Compare Products"}</button>
    </form>

    {session && !session.comparison_id && <section className="comparison-clarification" aria-live="polite">
      {entities.length >= 2 && attributes.length > 0 && <section className="generic-result comparison-preview" aria-label="Unverified comparison preview">
        <header className="generic-result-heading"><div><p className="eyebrow">COMPARISON PREVIEW</p><h2>Product comparison</h2></div><span className="generic-status">Not verified</span></header>
        <p className="generic-muted">No product values have been verified yet. Missing information is left blank rather than guessed.</p>
        <div className="generic-table-scroll"><table className="generic-comparison-table"><thead><tr><th scope="col">Attribute</th>{entities.map((entity) => <th scope="col" key={entity.key}>{entity.display_name}</th>)}</tr></thead><tbody>{attributes.map((attribute) => <tr key={attribute.key}><th scope="row">{attribute.label}</th>{entities.map((entity) => <td key={entity.key}><span className="generic-no-observation">Not verified</span></td>)}</tr>)}</tbody></table></div>
      </section>}
      {needsSource ? <div className="plain-clarification"><h2>Verified comparison data isn’t available yet</h2><p>We couldn’t verify product details for this comparison. Shopping links aren’t available yet either.</p></div> : awaitingConfirmation ? <div className="plain-clarification"><h2>Check your comparison</h2><p>Here’s what we’ll compare. If anything is wrong, edit the form above and submit again.</p><div className="comparison-understood"><p><strong>Products</strong><span>{entities.map((entity) => entity.display_name).join(" and ") || products.join(" and ")}</span></p><p><strong>Comparing</strong><span>{attributes.map((attribute) => attribute.label).join(", ") || selected.join(", ")}</span></p></div><label className="plain-confirm"><input type="checkbox" checked={reviewed} onChange={(event) => setReviewed(event.target.checked)} disabled={loading || busy} /> This matches what I want to compare</label><button type="button" className="generic-submit" onClick={confirmInterpretation} disabled={!reviewed || loading || busy}>{loading ? "Continuing..." : "Continue"}</button></div> : questions.length > 0 ? <div className="plain-clarification"><h2>One quick question</h2><ul>{questions.map((issue, index) => <li key={index}>{friendlyQuestion(issue, products)}{safeCandidates(issue).length > 0 && <div className="clarification-candidates">{safeCandidates(issue).map((candidate) => <button type="button" key={candidate} onClick={() => setClarificationAnswer(candidate)}>{candidate}</button>)}</div>}</li>)}</ul><form onSubmit={continueClarification}><label htmlFor="comparison-clarification-answer">Your answer</label><input id="comparison-clarification-answer" value={clarificationAnswer} onChange={(event) => setClarificationAnswer(event.target.value)} placeholder="Add a short detail" disabled={loading || busy} /><button type="submit" className="generic-submit" disabled={!clarificationAnswer.trim() || loading || busy}>{loading ? "Updating..." : "Continue"}</button></form></div> : null}
    </section>}
  </section>;
}
