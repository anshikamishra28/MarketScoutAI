"use client";

import { useState, type FormEvent } from "react";
import type { AttributeDefinition, ComparisonRequest, ComparisonValueType } from "../types/comparison";

interface ComparisonPromptProps {
  busy: boolean;
  error: string;
  onSubmit: (request: ComparisonRequest) => void;
}

interface AttributeDraft {
  label: string;
  valueType: ComparisonValueType;
  unit: string;
  currency: string;
  comparisonRule: string;
}

function keyFromLabel(value: string, fallback: string): string {
  const key = value.toLowerCase().trim().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "");
  return /^[a-z]/.test(key) ? key : `${fallback}_${key || "item"}`;
}

export function ComparisonPrompt({ busy, error, onSubmit }: ComparisonPromptProps) {
  const [requestText, setRequestText] = useState("");
  const [entities, setEntities] = useState(["", ""]);
  const [attributes, setAttributes] = useState<AttributeDraft[]>([
    { label: "", valueType: "scalar", unit: "", currency: "", comparisonRule: "" },
  ]);
  const [validationError, setValidationError] = useState("");

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const names = entities.map((name) => name.trim()).filter(Boolean);
    const dimensions = attributes.filter((attribute) => attribute.label.trim());
    if (!requestText.trim()) {
      setValidationError("Describe what you want to compare.");
      return;
    }
    if (names.length < 2) {
      setValidationError("Add at least two entities to compare.");
      return;
    }
    if (dimensions.length === 0) {
      setValidationError("Add at least one comparison attribute.");
      return;
    }
    const keys = new Set<string>();
    const definitions: AttributeDefinition[] = dimensions.map((attribute, index) => {
      const baseKey = keyFromLabel(attribute.label, "attribute");
      let key = baseKey;
      let suffix = 2;
      while (keys.has(key)) key = `${baseKey}_${suffix++}`;
      keys.add(key);
      return {
        key,
        label: attribute.label.trim(),
        value_type: attribute.valueType,
        unit: attribute.unit.trim() || null,
        currency: attribute.currency.trim() || null,
        comparison_rule: attribute.comparisonRule || null,
      };
    });
    const usedEntityKeys = new Set<string>();
    const request: ComparisonRequest = {
      user_request: requestText.trim(),
      entities: names.map((display_name, index) => {
        const baseKey = keyFromLabel(display_name, "entity");
        let key = baseKey;
        let suffix = 2;
        while (usedEntityKeys.has(key)) key = `${baseKey}_${suffix++}`;
        usedEntityKeys.add(key);
        return { key, display_name };
      }),
      attributes: definitions,
    };
    setValidationError("");
    onSubmit(request);
  }

  return (
    <section className="generic-comparison" aria-labelledby="generic-comparison-title">
      <div className="generic-comparison-heading">
        <p className="eyebrow">COMPARISON</p>
        <h2 id="generic-comparison-title">Compare options across a market</h2>
        <p className="muted">Set the entities and dimensions that matter to your decision.</p>
      </div>
      <form className="generic-comparison-form" onSubmit={submit}>
        <label className="generic-prompt-field">
          <span>What do you want to compare?</span>
          <textarea
            value={requestText}
            onChange={(event) => setRequestText(event.target.value)}
            placeholder="Describe the comparison and any useful context"
            rows={2}
            disabled={busy}
          />
        </label>

        <fieldset className="generic-fieldset">
          <legend>Entities</legend>
          {entities.map((entity, index) => (
            <div className="generic-entity-row" key={`entity-${index}`}>
              <label>
                <span>Entity {index + 1}</span>
                <input value={entity} onChange={(event) => setEntities((current) => current.map((item, i) => i === index ? event.target.value : item))} placeholder="Name an entity" disabled={busy} />
              </label>
              {entities.length > 2 && <button type="button" className="generic-remove" onClick={() => setEntities((current) => current.filter((_, i) => i !== index))} disabled={busy}>Remove</button>}
            </div>
          ))}
          <button type="button" className="generic-add" onClick={() => setEntities((current) => [...current, ""])} disabled={busy}>Add entity</button>
        </fieldset>

        <fieldset className="generic-fieldset">
          <legend>Comparison attributes</legend>
          {attributes.map((attribute, index) => (
            <div className="generic-attribute-row" key={`attribute-${index}`}>
              <label>
                <span>Attribute</span>
                <input value={attribute.label} onChange={(event) => setAttributes((current) => current.map((item, i) => i === index ? { ...item, label: event.target.value } : item))} placeholder="Name a dimension" disabled={busy} />
              </label>
              <label>
                <span>Value type</span>
                <select value={attribute.valueType} onChange={(event) => setAttributes((current) => current.map((item, i) => i === index ? { ...item, valueType: event.target.value as ComparisonValueType } : item))} disabled={busy}>
                  <option value="scalar">Scalar</option><option value="range">Range</option><option value="categorical">Categorical</option><option value="boolean">Boolean</option><option value="structured">Structured</option>
                </select>
              </label>
              <label>
                <span>Unit (optional)</span>
                <input value={attribute.unit} onChange={(event) => setAttributes((current) => current.map((item, i) => i === index ? { ...item, unit: event.target.value } : item))} placeholder="Unit" disabled={busy} />
              </label>
              <label>
                <span>Currency (optional)</span>
                <input value={attribute.currency} onChange={(event) => setAttributes((current) => current.map((item, i) => i === index ? { ...item, currency: event.target.value.toUpperCase() } : item))} placeholder="ISO code" maxLength={3} disabled={busy} />
              </label>
              <label>
                <span>Comparison rule</span>
                <select value={attribute.comparisonRule} onChange={(event) => setAttributes((current) => current.map((item, i) => i === index ? { ...item, comparisonRule: event.target.value } : item))} disabled={busy}>
                  <option value="">Report values only</option><option value="lower_is_better">Lower is better</option><option value="higher_is_better">Higher is better</option>
                </select>
              </label>
              {attributes.length > 1 && <button type="button" className="generic-remove" onClick={() => setAttributes((current) => current.filter((_, i) => i !== index))} disabled={busy}>Remove</button>}
            </div>
          ))}
          <button type="button" className="generic-add" onClick={() => setAttributes((current) => [...current, { label: "", valueType: "scalar", unit: "", currency: "", comparisonRule: "" }])} disabled={busy}>Add attribute</button>
        </fieldset>

        {(validationError || error) && <p className="generic-error" role="alert">{validationError || error}</p>}
        <button className="generic-submit" type="submit" disabled={busy}>{busy ? "Comparing..." : "Start comparison"}</button>
      </form>
    </section>
  );
}
