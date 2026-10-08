import type { Job } from '../api_jobs'

/** Progress bar + stage text + Cancel for a background job. The stage text is a polite live
 * region (announced when the stage changes); the bar is a progressbar with a text value. */
export default function JobProgress({
  job,
  onCancel,
  cancelling,
}: {
  job: Job
  onCancel: () => void
  cancelling: boolean
}) {
  const pct = Math.round(job.progress * 100)
  const stopping = job.status === 'cancelling' || cancelling
  return (
    <section
      aria-label="Analysis job progress"
      className="space-y-2 rounded-lg bg-navy-800 p-5"
      data-testid="job-progress"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="font-medium">
          Analysis job #{job.id}{' '}
          <span className="text-sm font-normal text-slate-300" data-testid="job-status">
            {job.status}
          </span>
        </h2>
        <button
          type="button"
          onClick={onCancel}
          disabled={stopping}
          className="rounded-md bg-navy-700 px-4 py-2 text-sm hover:bg-navy-600 disabled:opacity-50"
          data-testid="job-cancel"
        >
          {stopping ? 'Cancelling…' : 'Cancel analysis'}
        </button>
      </div>
      <div
        role="progressbar"
        aria-label="Analysis progress"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={pct}
        aria-valuetext={`${pct} percent, ${job.stage}`}
        className="h-3 w-full overflow-hidden rounded-full bg-navy-700"
      >
        <div className="h-full bg-accent transition-all" style={{ width: `${pct}%` }} />
      </div>
      <p className="text-sm text-slate-300" data-testid="job-stage">
        {pct}% ·{' '}
        <span aria-live="polite" role="status">
          {job.stage}
        </span>
      </p>
      <p className="text-xs text-slate-400">
        Cancelling stops at the next checkpoint (between clips and stages), not inside one export. Clips already
        exported and recorded stay recorded and are listed; half-written files are removed.
      </p>
    </section>
  )
}
