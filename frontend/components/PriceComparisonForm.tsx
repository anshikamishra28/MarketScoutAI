"use client";

import { useState, type FormEvent } from "react";
import type { PriceComparisonRequest } from "../types/price-comparison";

interface Props {
  busy: boolean;
  error: string;
  onSubmit: (request: PriceComparisonRequest) => void;
}

export function PriceComparisonForm({ busy, error, onSubmit }: Props) {
  const [brand, setBrand] = useState("");
  const [model, setModel] = useState("");
  const [modelNumber, setModelNumber] = useState("");
  const [ram, setRam] = useState("");
  const [storage, setStorage] = useState("");
  const [variant, setVariant] = useState("");
  const [retailerSelected, setRetailerSelected] = useState(true);
  const [validation, setValidation] = useState("");

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!brand.trim()) {
      setValidation("Enter a brand.");
      return;
    }
    if (!model.trim() && !modelNumber.trim()) {
      setValidation("Enter a model or model number.");
      return;
    }
    if (!retailerSelected) {
      setValidation("Select at least one currently available retailer.");
      return;
    }
    setValidation("");
    onSubmit({
      products: [{
        brand: brand.trim(),
        model: model.trim(),
        model_number: modelNumber.trim(),
        ram: ram.trim(),
        storage: storage.trim(),
        variant: variant.trim(),
      }],
      retailers: ["reliance_digital"],
    });
  }

  return (
    <form className="comparison-form" onSubmit={submit}>
      <div className="comparison-form-heading">
        <div><p className="eyebrow">PRICE COMPARISON</p><h2>Compare retailer prices</h2>
          <p className="muted">Check observed product page prices and exact variant matches across available retailers.</p></div>
      </div>
      <div className="comparison-fields">
        <label>Brand <span aria-hidden="true">*</span><input value={brand} onChange={(e) => setBrand(e.target.value)} placeholder="e.g. OnePlus" required /></label>
        <label>Model<input value={model} onChange={(e) => setModel(e.target.value)} placeholder="e.g. Nord 4" /></label>
        <label>Model number<input value={modelNumber} onChange={(e) => setModelNumber(e.target.value)} placeholder="Optional" /></label>
        <label>RAM<input value={ram} onChange={(e) => setRam(e.target.value)} placeholder="e.g. 8GB" /></label>
        <label>Storage<input value={storage} onChange={(e) => setStorage(e.target.value)} placeholder="e.g. 128GB" /></label>
        <label>Variant<input value={variant} onChange={(e) => setVariant(e.target.value)} placeholder="e.g. colour or edition" /></label>
      </div>
      <fieldset className="retailer-picker">
        <legend>Retailers</legend>
        <label><input type="checkbox" checked={retailerSelected} onChange={(e) => setRetailerSelected(e.target.checked)} /> Reliance Digital <small>Available</small></label>
      </fieldset>
      {(validation || error) && <p className="comparison-error" role="alert">{validation || error}</p>}
      <button className="comparison-submit" type="submit" disabled={busy}>{busy ? "Checking retailer…" : "Compare prices"}</button>
      <p className="comparison-note">Only prices explicitly observed on accepted product pages are shown. Retailer access and product matching can vary.</p>
    </form>
  );
}
