import type { ErrorRates } from './api'

const pct = (v: number | null | undefined) => (v == null ? 'n/a' : `${(v * 100).toFixed(1)}%`)
const ci = (c: (number | null)[]) => `${pct(c[0])} to ${pct(c[1])}`

/** Measured error rates for the model/config used by a run, with the data they came from. */
export default function ErrorRatePanel({ rates, classes }: { rates: ErrorRates; classes?: string[] }) {
  const unmeasured = classes?.filter((c) => !(rates.measured_classes ?? []).includes(c)) ?? []
  return (
    <div className="space-y-2 rounded bg-navy-900 p-3 text-xs" data-testid="error-rates">
      <div className="font-medium text-slate-200">Measured error rates (95% CI, Wilson)</div>
      {rates.configs.length === 0 ? (
        <p className="text-amber-300">
          {rates.note ?? 'No error rates measured for this configuration. Treat reliability as unknown.'}
        </p>
      ) : (
        <table className="w-full text-left">
          <caption className="sr-only">Measured error rates for this model configuration</caption>
          <thead className="text-slate-400">
            <tr>
              <th scope="col" className="py-1">Data</th>
              <th scope="col">Condition</th>
              <th scope="col">Conf.</th>
              <th scope="col">Precision</th>
              <th scope="col">Recall</th>
              <th scope="col">n</th>
            </tr>
          </thead>
          <tbody>
            {rates.configs.map((c, i) => (
              <tr key={i} className="border-t border-navy-700 align-top" data-testid="error-rate-row">
                <td className="py-1 pr-2">
                  {c.dataset}
                  <div className="text-amber-300">{c.label}</div>
                </td>
                <td>{c.condition}</td>
                <td>{c.confidence_threshold ?? 'n/a'}</td>
                <td>
                  {pct(c.precision)}
                  <div className="text-slate-400">{ci(c.precision_ci_wilson)}</div>
                </td>
                <td>
                  {pct(c.recall)}
                  <div className="text-slate-400">{ci(c.recall_ci_wilson)}</div>
                </td>
                <td>{c.n_images}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {rates.run_threshold_measured === false && (
        <p className="text-amber-300">The confidence threshold used in this run was not one of the measured values.</p>
      )}
      {rates.run_params_match_measured === false && (
        <p className="text-amber-300">These parameters differ from the measured configuration; the numbers may not apply.</p>
      )}
      {unmeasured.length > 0 && (
        <p className="text-amber-300" data-testid="unmeasured-classes">
          No error rate was measured for: {unmeasured.join(', ')}.
        </p>
      )}
      {rates.unmeasured_note && <p className="text-slate-400">{rates.unmeasured_note}</p>}
      <p className="text-slate-400">
        Nothing was validated on real DVR footage. Public-benchmark numbers will not transfer to low-resolution,
        highly compressed DVR footage.
      </p>
    </div>
  )
}
