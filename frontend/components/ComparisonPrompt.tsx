"use client";

import { useState, type FormEvent } from "react";
import type {
  AttributeDefinition,
  ComparisonRequest,
  ComparisonValueType,
  EntityReference,
  IdentifierDraft,
  SourceReference,
} from "../types/comparison";

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

interface EntityDraft {
  displayName: string;
  identifiers: IdentifierDraft[];
}

const AVAILABLE_SOURCES: SourceReference[] = [
  {
    key: "reliance_digital",
    name: "Reliance Digital",
    source_type: "retailer",
    url: "https://www.reliancedigital.in/",
  },
];

function keyFromLabel(value: string, fallback: string): string {
  const key = value.toLowerCase().trim().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "");
  return /^[a-z]/.test(key) ? key : `${fallback}_${key || "item"}`;
}

function uniqueKey(baseKey: string, used: Set<string>): string {
  let key = baseKey;
  let suffix = 2;
  while (used.has(key)) key = `${baseKey}_${suffix++}`;
  used.add(key);
  return key;
}

export function ComparisonPrompt({ busy, error, onSubmit }: ComparisonPromptProps) {
  const [requestText, setRequestText] = useState("");
  const [entities, setEntities] = useState<EntityDraft[]>([
    { displayName: "", identifiers: [] },
    { displayName: "", identifiers: [] },
  ]);
  const [attributes, setAttributes] = useState<AttributeDraft[]>([
    { label: "", valueType: "scalar", unit: "", currency: "", comparisonRule: "" },
  ]);
  const [selectedSourceKeys, setSelectedSourceKeys] = useState<string[]>([]);
  const [validationError, setValidationError] = useState("");

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const namedEntities = entities.filter((entity) => entity.displayName.trim());
    const dimensions = attributes.filter((attribute) => attribute.label.trim());
    if (!requestText.trim()) {
      setValidationError("Describe what you want to compare.");
      return;
    }
    if (namedEntities.length < 2) {
      setValidationError("Add at least two entities to compare.");
      return;
    }
    if (dimensions.length === 0) {
      setValidationError("Add at least one comparison attribute.");
      return;
    }
    if (selectedSourceKeys.length === 0) {
      setValidationError("Select at least one comparison source.");
      return;
    }

    const usedAttributeKeys = new Set<string>();
    const definitions: AttributeDefinition[] = dimensions.map((attribute) => ({
      key: uniqueKey(keyFromLabel(attribute.label, "attribute"), usedAttributeKeys),
      label: attribute.label.trim(),
      value_type: attribute.valueType,
      unit: attribute.unit.trim() || null,
      currency: attribute.currency.trim() || null,
      comparison_rule: attribute.comparisonRule || null,
    }));

    const usedEntityKeys = new Set<string>();
    const entityReferences: EntityReference[] = namedEntities.map((entity) => {
      const identifiers: Record<string, string> = {};
      for (const identifier of entity.identifiers) {
        const key = identifier.key.trim();
        const value = identifier.value.trim();
        if (key && value) identifiers[key] = value;
      }
      return {
        key: uniqueKey(keyFromLabel(entity.displayName, "entity"), usedEntityKeys),
        display_name: entity.displayName.trim(),
        identifiers,
      };
    });

    const selectedSources = AVAILABLE_SOURCES.filter((source) => selectedSourceKeys.includes(source.key));
    const request: ComparisonRequest = {
      user_request: requestText.trim(),
      entities: entityReferences,
      attributes: definitions,
      source_preferences: selectedSources,
    };
    setValidationError("");
    onSubmit(request);
  }

  function updateEntity(index: number, update: (entity: EntityDraft) => EntityDraft) {
    setEntities((current) => current.map((entity, itemIndex) => itemIndex === index ? update(entity) : entity));
  }

  function updateIdentifier(entityIndex: number, identifierIndex: number, patch: Partial<IdentifierDraft>) {
    updateEntity(entityIndex, (entity) => ({
      ...entity,
      identifiers: entity.identifiers.map((identifier, itemIndex) => itemIndex === identifierIndex
        ? { ...identifier, ...patch }
        : identifier),
    }));
  }

  return (
    <section className="generic-comparison" aria-labelledby="generic-comparison-title">
      <div className="generic-comparison-heading">
        <p className="eyebrow">COMPARISON</p>
        <h2 id="generic-comparison-title">Compare options across a market</h2>
        <p className="muted">Set the entities, identity details, sources, and dimensions that matter to your decision.</p>
      </div>
      <form className="generic-comparison-form" onSubmit={submit}>
        <label className="generic-prompt-field">
          <span>What do you want to compare?</span>
          <textarea value={requestText} onChange={(event) => setRequestText(event.target.value)} placeholder="Describe the comparison and any useful context" rows={2} disabled={busy} />
        </label>

        <fieldset className="generic-fieldset">
          <legend>Entities</legend>
          {entities.map((entity, index) => (
            <div className="generic-entity-card" key={`entity-${index}`}>
              <div className="generic-entity-row">
                <label>
                  <span>Entity {index + 1}</span>
                  <input value={entity.displayName} onChange={(event) => updateEntity(index, (current) => ({ ...current, displayName: event.target.value }))} placeholder="Name an entity" disabled={busy} />
                </label>
                {entities.length > 2 && <button type="button" className="generic-remove" onClick={() => setEntities((current) => current.filter((_, itemIndex) => itemIndex !== index))} disabled={busy}>Remove entity</button>}
              </div>
              <div className="generic-identifiers-heading">
                <span>Identifiers (optional)</span>
                <button type="button" className="generic-add" onClick={() => updateEntity(index, (current) => ({ ...current, identifiers: [...current.identifiers, { key: "", value: "" }] }))} disabled={busy}>Add identifier</button>
              </div>
              {entity.identifiers.map((identifier, identifierIndex) => (
                <div className="generic-identifier-row" key={`identifier-${index}-${identifierIndex}`}>
                  <label>
                    <span>Key</span>
                    <input value={identifier.key} onChange={(event) => updateIdentifier(index, identifierIndex, { key: event.target.value })} placeholder="Identifier name" disabled={busy} />
                  </label>
                  <label>
                    <span>Value</span>
                    <input value={identifier.value} onChange={(event) => updateIdentifier(index, identifierIndex, { value: event.target.value })} placeholder="Identifier value" disabled={busy} />
                  </label>
                  <button type="button" className="generic-remove" onClick={() => updateEntity(index, (current) => ({ ...current, identifiers: current.identifiers.filter((_, itemIndex) => itemIndex !== identifierIndex) }))} disabled={busy}>Remove</button>
                </div>
              ))}
            </div>
          ))}
          <button type="button" className="generic-add" onClick={() => setEntities((current) => [...current, { displayName: "", identifiers: [] }])} disabled={busy}>Add entity</button>
        </fieldset>

        <fieldset className="generic-fieldset">
          <legend>Comparison sources</legend>
          <div className="generic-source-options">
            {AVAILABLE_SOURCES.map((source) => (
              <label className="generic-source-option" key={source.key}>
                <input
                  type="checkbox"
                  checked={selectedSourceKeys.includes(source.key)}
                  onChange={(event) => setSelectedSourceKeys((current) => event.target.checked
                    ? [...current, source.key]
                    : current.filter((key) => key !== source.key))}
                  disabled={busy}
                />
                <span>{source.name}</span>
                {source.source_type && <small>{source.source_type}</small>}
              </label>
            ))}
          </div>
        </fieldset>

        <fieldset className="generic-fieldset">
          <legend>Comparison attributes</legend>
          {attributes.map((attribute, index) => (
            <div className="generic-attribute-row" key={`attribute-${index}`}>
              <label>
                <span>Attribute</span>
                <input value={attribute.label} onChange={(event) => setAttributes((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, label: event.target.value } : item))} placeholder="Name a dimension" disabled={busy} />
              </label>
              <label>
                <span>Value type</span>
                <select value={attribute.valueType} onChange={(event) => setAttributes((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, valueType: event.target.value as ComparisonValueType } : item))} disabled={busy}>
                  <option value="scalar">Scalar</option><option value="range">Range</option><option value="categorical">Categorical</option><option value="boolean">Boolean</option><option value="structured">Structured</option>
                </select>
              </label>
              <label>
                <span>Unit (optional)</span>
                <input value={attribute.unit} onChange={(event) => setAttributes((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, unit: event.target.value } : item))} placeholder="Unit" disabled={busy} />
              </label>
              <label>
                <span>Currency (optional)</span>
                <input value={attribute.currency} onChange={(event) => setAttributes((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, currency: event.target.value.toUpperCase() } : item))} placeholder="ISO code" maxLength={3} disabled={busy} />
              </label>
              <label>
                <span>Comparison rule</span>
                <select value={attribute.comparisonRule} onChange={(event) => setAttributes((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, comparisonRule: event.target.value } : item))} disabled={busy}>
                  <option value="">Report values only</option><option value="lower_is_better">Lower is better</option><option value="higher_is_better">Higher is better</option>
                </select>
              </label>
              {attributes.length > 1 && <button type="button" className="generic-remove" onClick={() => setAttributes((current) => current.filter((_, itemIndex) => itemIndex !== index))} disabled={busy}>Remove</button>}
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
