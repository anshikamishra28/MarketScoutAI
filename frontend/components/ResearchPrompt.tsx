import type { FormEvent } from "react";

interface ResearchPromptProps {
  question: string;
  busy: boolean;
  error: string;
  onQuestionChange: (question: string) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
}

const suggestions = [
  "India's electric two-wheeler market",
  "Affordable skincare brands in India",
  "AI coding tools for small teams",
];

export function ResearchPrompt({ question, busy, error, onQuestionChange, onSubmit }: ResearchPromptProps) {
  return <section className="hero">
    <p className="eyebrow">MARKET INTELLIGENCE WORKSPACE</p>
    <h1>Research markets.<br /><em>See the evidence.</em></h1>
    <p className="lede">Define a market question. Follow the research as it runs, inspect the evidence and coverage, then review the final analysis.</p>
    <form onSubmit={onSubmit} className="search">
      <textarea value={question} onChange={(event) => onQuestionChange(event.target.value)} minLength={8} maxLength={2000} required
        aria-label="Research question" placeholder="Analyze the Indian smartphone market under ₹30,000" />
      <button disabled={busy || question.trim().length < 8}>{busy ? "Research running…" : "Start research →"}</button>
    </form>
    {error && <p className="error" role="alert">{error}</p>}
    <div className="suggestions"><span>Example questions</span>
      {suggestions.map((suggestion) => <button key={suggestion} onClick={() => onQuestionChange(suggestion)} type="button">{suggestion}</button>)}
    </div>
  </section>;
}
