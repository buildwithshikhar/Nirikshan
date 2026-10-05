import { useState } from 'react'
import type { ChainResult } from '../api'

/** Custody chain head with a copy button. Record it outside the system to detect truncation. */
export default function HeadHash({ chain }: { chain: ChainResult | null }) {
  const [copied, setCopied] = useState(false)
  if (!chain) return null

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(chain.head_hash)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      // clipboard unavailable (insecure context): the hash stays selectable on screen
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-2 text-xs" data-testid="head-hash">
      <span className="text-slate-400">Custody head_hash ({chain.entries} entries):</span>
      <code className="break-all font-mono text-[11px]">{chain.head_hash}</code>
      <button className="rounded bg-navy-700 px-2 py-0.5 hover:bg-navy-900" onClick={copy}>
        {copied ? 'Copied' : 'Copy'}
      </button>
      <span className="text-slate-500">
        Record this outside the system; a truncated log is only detectable against it.
      </span>
    </div>
  )
}
