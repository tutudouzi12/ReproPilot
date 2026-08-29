import { Activity, AlertTriangle, CheckCircle2, ShieldCheck, XCircle } from 'lucide-react';
import type { RunAssessment } from '../../contracts/api';

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

interface AssessmentStatus {
  version?: string;
  status?: string;
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
  const assessment = parseRecord<RunAssessment>(raw);
  if (assessment?.version === 'autoresearch.assessment/v1') {
    const outcomePassed = assessment.outcome.status === 'passed';
    const integrityVerified = assessment.evidence.integrity === 'verified';
    const complianceOk = assessment.compliance.status === 'verified';
    const validationRuns = (assessment.outcome.validation_passed_runs ?? 0) + (assessment.outcome.validation_failed_runs ?? 0);
    return (
      <div className="autoresearch-view">
        <div className={`autoresearch-verdict ${outcomePassed && complianceOk ? 'is-kept' : 'is-rejected'}`}>
          {outcomePassed && complianceOk ? <ShieldCheck /> : <AlertTriangle />}
          <div>
            <strong>{outcomePassed ? 'Outcome verified' : assessment.outcome.status === 'failed' ? 'Outcome not accepted' : 'Outcome not assessable'}</strong>
            <span>{assessment.outcome.validation_mode?.replaceAll('_', ' ') ?? 'validation not run'}</span>
          </div>
        </div>
        <div className="autoresearch-dimensions">
          <Dimension label="Outcome" value={assessment.outcome.status} ok={outcomePassed} />
          <Dimension label="Compliance" value={assessment.compliance.status} ok={complianceOk} />
          <Dimension label="Process" value={assessment.process.status} ok={assessment.process.status === 'complete'} />
        </div>
        <div className="autoresearch-metrics">
          <Metric label="Baseline" value={score(assessment.outcome.baseline_score)} />
          <Metric label="Best" value={score(assessment.outcome.best_score)} />
          <Metric label="Improvement" value={score(assessment.outcome.directional_improvement)} />
        </div>
        <div className="autoresearch-integrity">
          <Integrity label={integrityVerified ? 'Hash-linked trajectory' : 'Legacy evidence only'} ok={integrityVerified} />
          <Integrity label="Source bindings" ok={assessment.evidence.source_bindings_verified === true} partial={assessment.evidence.source_bindings_verified == null} />
        </div>
        <div className="autoresearch-assessment-facts">
          <span>{assessment.outcome.metric_key ?? 'metric'} · validation {assessment.outcome.validation_status}</span>
          <span>{validationRuns > 0 ? `${assessment.outcome.validation_passed_runs ?? 0}/${validationRuns} validation runs` : 'no validation runs'}</span>
          <span>{assessment.process.event_count == null ? 'event history unavailable' : `${assessment.process.event_count} verified events`}</span>
          <span>{assessment.process.accepted_trials ?? 0}/{assessment.process.completed_trials ?? 0} trials kept · {assessment.process.rollback_count ?? '—'} rollbacks</span>
        </div>
        {!integrityVerified && <p className="autoresearch-warning">Partial assessment: this historical run has no verifiable hash-linked trajectory.</p>}
        {assessment.compliance.hard_violation_reasons.length > 0 && (
          <p className="autoresearch-reason">Hard violation: {assessment.compliance.hard_violation_reasons.join(', ').replaceAll('_', ' ')}</p>
        )}
        <p className="autoresearch-no-score">No composite score is calculated; the three dimensions remain raw facts.</p>
      </div>
    );
  }

  const assessmentStatus = parseRecord<AssessmentStatus>(raw);
  if (assessmentStatus?.version === 'autoresearch.assessment-status/v1') {
    return (
      <div className="autoresearch-view">
        <div className="autoresearch-verdict is-rejected">
          <AlertTriangle />
          <div><strong>Assessment generation blocked</strong><span>integrity not established</span></div>
        </div>
        <p className="autoresearch-reason">{assessmentStatus.reason || 'Required source evidence is unavailable.'}</p>
      </div>
    );
  }

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

function Dimension({ label, value, ok }: { label: string; value: string; ok: boolean }) {
  return <div className={ok ? 'is-valid' : 'is-invalid'}><span>{label}</span><strong>{value.replaceAll('_', ' ')}</strong></div>;
}

function Integrity({ label, ok, partial = false }: { label: string; ok?: boolean; partial?: boolean }) {
  return <div className={partial ? 'is-partial' : ok ? 'is-valid' : 'is-invalid'}>{partial ? <AlertTriangle /> : ok ? <CheckCircle2 /> : <XCircle />}<span>{label}</span></div>;
}
