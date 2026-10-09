import { useState } from 'react'
import { errorText } from '../../lib/http'
import { Button, Chip, useToast } from '../../ui'
import { type ChainResult, integrityApi } from './api'

/** "Verify chain" button + result: CHAIN VALID / CHAIN INVALID with each failing entry. */
export function ChainVerify({ caseId, onResult }: { caseId: number; onResult?: (r: ChainResult) => void }) {
  const toast = useToast()
  const [res, setRes] = useState<ChainResult | null>(null)
  const [busy, setBusy] = useState(false)
  const run = async () => {
    setBusy(true)
    try {
      const r = await integrityApi.verifyChain(caseId)
      setRes(r)
      onResult?.(r)
    } catch (e) {
      toast.error(errorText(e))
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="flex flex-wrap items-start gap-4">
      <Button variant="primary" busy={busy} onClick={run}>Verify chain and signatures</Button>
      <div data-testid="chain-result" role="status" aria-live="polite" className="text-sm">
        {res && (
          <>
            <Chip tone={res.ok ? 'ok' : 'bad'}>{res.ok ? 'CHAIN VALID' : 'CHAIN INVALID'}</Chip>{' '}
            <span>{res.entries} entries, key {res.key_id}</span>
            {res.failures.map((f, i) => (
              <div key={i} className="text-red-300">entry {f.seq}: {f.reason}</div>
            ))}
          </>
        )}
      </div>
    </div>
  )
}
