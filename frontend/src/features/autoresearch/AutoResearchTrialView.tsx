import { Activity, CheckCircle2, ShieldCheck, XCircle } from 'lucide-react';

interface Trial {
  number?: number;
  status?: string;
  decision?: string;
  hypothesis?: string;
  reason?: string;
  metric?: number | null;
  metric_samples?: number[];
  metric_stddev?: number;
  patches?: Array<{ path?: string }>;
}

interface TrialLedger {
  version?: string;
  status?: string;
  metric_key?: string;
  baseline_score?: number;
  best_score?: number;
  completed_trials?: number;
  accepted_trials?: number;
  max_trials?: number;
  stop_reason?: string;
  trials?: Trial[];
  model_usage?: {
    provider?: string;
    model?: string;
    request_count?: number;
    reported_request_count?: number;
    prompt_tokens?: number;
    completion_tokens?: number;
    total_tokens?: number;
  };
}

interface ValidationReport {
  version?: string;
  status?: string;
  validation_mode?: string;
  expected_score?: number;
  observed_score?: number;
  observed_scores?: number[];
  passed_runs?: number;
  failed_runs?: number;
  candidate_intact?: boolean;
  protected_files_intact?: boolean;
  reason?: string;
}

const parseRecord = <T extends object>(raw: string): T | null => {
  try {
    const value = JSON.parse(raw) as unknown;
    return value !== null && typeof value === 'object' && !Array.isArray(value) ? value as T : null;
  } catch {
    return null;
  }
};

const score = (value: number | undefined | null) => typeof value === 'number' && Number.isFinite(value) ? value.toFixed(4) : '\u2014';

export function AutoResearchTrialView({ raw, taskType }: { raw: string; taskType?: string }) {
  const validation = taskType === 'autoresearch_validate' ? parseRecord<ValidationReport>(raw) : null;
  if (validation?.version === 'autoresearch.validation/v1') {
    const passed = validation.status === 'passed';
    return (
      <div className="autoresearch-view">
        <div className={`autoresearch-verdict ${passed ? 'is-kept' : 'is-rejected'}`}>
          {passed ? <ShieldCheck /> : <XCircle />}
          <div>
            <strong>{passed ? 'Independent validation passed' : 'Independent validation failed'}</strong>
            <span>{(validation.validation_mode ?? 'validation').replaceAll('_', ' ')}</span>
          </div>
        </div>
        <div className="autoresearch-metrics">
          <Metric label="Expected" value={score(validation.expected_score)} />
          <Metric label="Observed" value={score(validation.observed_score)} />
          <Metric label="Runs" value={`${validation.passed_runs ?? 0}/${(validation.passed_runs ?? 0) + (validation.failed_runs ?? 0)}`} />
        </div>
        <div className="autoresearch-integrity">
          <Integrity label="Candidate hash" ok={validation.candidate_intact} />
          <Integrity label="Protected files" ok={validation.protected_files_intact} />
        </div>
        {validation.observed_scores && <div className="autoresearch-samples">Fresh scores {'\u00b7'} {validation.observed_scores.map(score).join(' \u00b7 ')}</div>}
        {validation.reason && <p className="autoresearch-reason">{validation.reason}</p>}
      </div>
    );
  }

  const ledger = parseRecord<TrialLedger>(raw);
  if (ledger?.version !== 'autoresearch.ledger/v1') return <div className="execution-empty-state">Trial ledger will appear after the AutoResearch node runs.</div>;
  return (
    <div className="autoresearch-view">
      <div className="autoresearch-metrics">
        <Metric label="Baseline" value={score(ledger.baseline_score)} />
        <Metric label="Best" value={score(ledger.best_score)} />
        <Metric label="Kept" value={`${ledger.accepted_trials ?? 0}/${ledger.completed_trials ?? 0}`} />
      </div>
      <div className="autoresearch-stop">
        <Activity />
        <span>{ledger.metric_key ?? 'metric'}</span>
        <strong>{(ledger.stop_reason ?? ledger.status ?? 'running').replaceAll('_', ' ')}</strong>
      </div>
      {(ledger.model_usage?.request_count ?? 0) > 0 && (
        <div className="autoresearch-usage">
          <span>{ledger.model_usage?.model || ledger.model_usage?.provider || 'model'}</span>
          <strong>{ledger.model_usage?.request_count} requests · {ledger.model_usage?.total_tokens ?? 0} tokens</strong>
        </div>
      )}
      <div className="autoresearch-trials">
        {(ledger.trials ?? []).map((trial) => {
          const kept = trial.decision === 'keep';
          const baseline = trial.status === 'baseline';
          return (
            <div key={`${trial.number}-${trial.status}`} className={`autoresearch-trial ${kept ? 'is-kept' : baseline ? 'is-baseline' : 'is-rejected'}`}>
              <span className="autoresearch-trial__marker">{kept || baseline ? <CheckCircle2 /> : <XCircle />}</span>
              <div className="autoresearch-trial__copy">
                <div>
                  <strong>{trial.number === 0 ? 'Baseline' : `Trial ${trial.number}`}</strong>
                  <span>{trial.status ?? trial.decision}</span>
                  <b>{score(trial.metric)}</b>
                </div>
                <p>{trial.hypothesis || trial.reason || 'No hypothesis recorded.'}</p>
                <small>
                  {(trial.metric_samples?.length ?? 0) > 1 ? `${trial.metric_samples?.length} runs \u00b7 \u03c3 ${score(trial.metric_stddev)}` : 'single measurement'}
                  {(trial.patches?.length ?? 0) > 0 ? ` \u00b7 ${trial.patches?.length} file patch` : ''}
                </small>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return <div><span>{label}</span><strong>{value}</strong></div>;
}

function Integrity({ label, ok }: { label: string; ok?: boolean }) {
  return <div className={ok ? 'is-valid' : 'is-invalid'}>{ok ? <CheckCircle2 /> : <XCircle />}<span>{label}</span></div>;
}
